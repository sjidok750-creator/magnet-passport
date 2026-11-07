# adsb.lol 의 하루치 전 세계 비행 기록에서 공항별 출발·도착 표를 뽑는다.
# 자료: github.com/adsblol/globe_history_2026 (ODbL), 노선: vradarserver/standing-data (CC0).
#
#   python -I tools/harvest_flights.py <day.tar.aa 가 있는 폴더> <YYYY-MM-DD> <출력 폴더> [표본 개수]
#
# 받은 자료는 읽기만 한다. 결과: <출력>/<날짜>/<IATA>.json, <출력>/<날짜>/t/<IATA>.json(궤적)
import collections
import csv
import gzip
import io
import json
import math
import os
import re
import sys
import tarfile
import time
import zipfile
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
VRS_ZIP = os.environ.get('MP_VRS') or os.path.join(HERE, '..', 'cache', 'adsb', 'vrs', 'standing.zip')
CALL = re.compile(r'^[A-Z]{3}[0-9][0-9A-Z]{0,4}$')
NEAR_KM = 25          # 구간 시작·끝이 이 안에 있어야 그 공항으로 본다
LOW_FT = 5000         # 공항 표고에서 이 높이 아래
GAP_S = 1200          # 낮은 고도에서 이만큼 끊기면 다른 구간
MIN_KM = 100
# 여객기만 남긴다. 화물 전문 회사, 소형 업무용기, 화물·전세용 8000번대 이상 편명을 뺀다.
CARGO = set('FDX UPS GTI PAC CKS CLX ABX ATN DHK DHL BCS BOX DAE AHK SWN NCA ABW CAO CYZ CSS YZR CKK GEC TAY SOO MNB ICL ICV AZG VDA ABD SQC AMF WGN KFS AJT RCH TGX CPT LCO HKC GSS WOA NPT MPH CAL5'.split())
AIRLINER = re.compile(r'^(A[123]\d|B[37]\d|BCS|E1[79]|E29|E75|E19|E[14]\d|CRJ|AT[47]|DH8|C919|ARJ|AJ27|SU9|SF34|B46|RJ\d|F70|F100|MD[89]|A148|T204|IL96|D328|J328)')
KM_PER_MIN = 13.5     # 안 보인 구간의 시간 추정


def km(a, b, c, d):
    r = math.radians
    x = math.sin(r(c - a) / 2) ** 2 + math.cos(r(a)) * math.cos(r(c)) * math.sin(r(d - b) / 2) ** 2
    return 12742 * math.asin(min(1, math.sqrt(x)))


class Parts(io.RawIOBase):
    """나뉜 tar 조각을 한 파일처럼 읽는다."""

    def __init__(self, paths):
        self.paths = list(paths)
        self.f = open(self.paths.pop(0), 'rb')

    def readable(self):
        return True

    def readinto(self, b):
        while True:
            n = self.f.readinto(b)
            if n:
                return n
            self.f.close()
            if not self.paths:
                return 0
            self.f = open(self.paths.pop(0), 'rb')


def load_airports():
    # [IATA, ICAO, 위도, 경도, 표고(피트)]
    with open(os.path.join(HERE, 'airports_elev.json'), encoding='utf8') as f:
        return [tuple(a) for a in json.load(f)]


AIRPORTS = None
GRID = None
FREIGHT = set()


def init_worker():
    global AIRPORTS, GRID, FREIGHT
    AIRPORTS = load_airports()
    FREIGHT = freight_airlines()
    GRID = collections.defaultdict(list)
    for i, a in enumerate(AIRPORTS):
        GRID[(math.floor(a[2] * 2), math.floor(a[3] * 2))].append(i)


def nearest(lat, lon, alt):
    """낮게 있는 점 가까이의 공항 번호. 없으면 None."""
    cx, cy = math.floor(lat * 2), math.floor(lon * 2)
    best, dist = None, NEAR_KM
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for i in GRID.get((cx + dx, cy + dy), ()):
                a = AIRPORTS[i]
                if alt - a[4] > LOW_FT:
                    continue
                d = km(lat, lon, a[2], a[3])
                if d < dist:
                    best, dist = i, d
    return best


def segments(trace, t0):
    """공중에 있던 구간들. 바닥에 닿거나, 낮은 고도에서 오래 끊기면 나눈다."""
    out, seg, call, last = [], [], None, None
    for r in trace:
        t = t0 + r[0]
        det = r[8] if len(r) > 8 else None
        if isinstance(det, dict) and det.get('flight'):
            call = det['flight'].strip()
        lat, lon, alt = r[1], r[2], r[3]
        if lat is None or lon is None:
            continue
        if alt == 'ground':
            if seg:
                out.append(seg)
                seg = []
            last = None
            continue
        if alt is None:
            alt = last[3] if last else 0
        if seg and t - last[0] > GAP_S and (last[3] < 14000 or alt < 14000):
            out.append(seg)
            seg = []
        last = (t, lat, lon, alt, call)
        seg.append(last)
    if seg:
        out.append(seg)
    return out


def passenger(call, kind):
    if call[:3] in CARGO or call[:3] in FREIGHT:
        return False
    digits = call[3:]
    if digits.isdigit() and int(digits) >= 8000:
        return False
    return not kind or bool(AIRLINER.match(kind))


def read_trace(blob):
    """trace 파일 하나 → 구간 목록."""
    try:
        d = json.loads(gzip.decompress(blob) if blob[:2] == b'\x1f\x8b' else blob)
    except (OSError, ValueError, EOFError):
        return []
    legs = []
    for seg in segments(d.get('trace') or [], d.get('timestamp') or 0):
        if len(seg) < 4 or seg[-1][0] - seg[0][0] < 600:
            continue
        calls = collections.Counter(p[4] for p in seg if p[4])
        if not calls:
            continue
        call = calls.most_common(1)[0][0]
        if not CALL.match(call) or not passenger(call, d.get('t') or ''):
            continue
        a, b = seg[0], seg[-1]
        origin = nearest(a[1], a[2], a[3])
        dest = nearest(b[1], b[2], b[3])
        if origin is not None and origin == dest:
            continue
        step = max(150, (b[0] - a[0]) / 36)
        track, next_t = [], 0
        for p in seg:
            if p[0] >= next_t:
                track.append((round(p[2], 2), round(p[1], 2)))
                next_t = p[0] + step
        track.append((round(b[2], 2), round(b[1], 2)))
        legs.append((d.get('t') or '', call, a[0], b[0], origin, dest, a[1], a[2], b[1], b[2], track))
    return legs


def work(batch):
    out = []
    for blob in batch:
        out.extend(read_trace(blob))
    return out


def batches(paths, size, limit):
    stream = io.BufferedReader(Parts(paths), 1 << 20)
    n = 0
    with tarfile.open(fileobj=stream, mode='r|') as tar:
        batch = []
        for m in tar:
            if not m.isfile() or 'trace_full_' not in m.name:
                continue
            batch.append(tar.extractfile(m).read())
            n += 1
            if len(batch) == size:
                yield batch
                batch = []
            if limit and n >= limit:
                break
        if batch:
            yield batch


def freight_airlines():
    z = zipfile.ZipFile(VRS_ZIP)
    name = next(n for n in z.namelist() if n.endswith('/airlines/schema-01/airlines.csv'))
    out = set()
    for row in csv.DictReader(io.TextIOWrapper(z.open(name), encoding='utf-8-sig')):
        if row.get('ICAO') and re.search(r'cargo|freight|parcel|logistic|courier|overnight', row.get('Name') or '', re.I):
            out.add(row['ICAO'])
    return out


def load_routes(by_icao):
    """편명 → 지나는 공항 번호 목록, 항공사 ICAO → IATA."""
    z = zipfile.ZipFile(VRS_ZIP)
    routes, airlines = {}, {}
    for name in z.namelist():
        if '/routes/schema-01/' in name and name.endswith('.csv'):
            for row in csv.DictReader(io.TextIOWrapper(z.open(name), encoding='utf-8-sig')):
                path = [by_icao.get(c) for c in (row.get('AirportCodes') or '').split('-')]
                routes[row['Callsign']] = path
        if name.endswith('/airlines/schema-01/airlines.csv'):
            for row in csv.DictReader(io.TextIOWrapper(z.open(name), encoding='utf-8-sig')):
                if row.get('ICAO') and row.get('IATA'):
                    airlines[row['ICAO']] = row['IATA']
    return routes, airlines


def fill(leg, routes, airports):
    """한쪽 공항이 안 보인 구간을 노선 자료로 채운다. 시각은 거리로 추정한다."""
    kind, call, t1, t2, origin, dest, la, lo, lb, lc, track = leg
    observed = origin is not None and dest is not None
    path = routes.get(call)
    if not observed and path:
        pairs = [(path[i], path[i + 1]) for i in range(len(path) - 1)]
        if origin is not None:
            pairs = [p for p in pairs if p[0] == origin]
        elif dest is not None:
            pairs = [p for p in pairs if p[1] == dest]
        best, score = None, 1e9
        for x, y in pairs:
            if x is None or y is None:
                continue
            ax, ay = airports[x], airports[y]
            s = km(ax[2], ax[3], la, lo) + km(la, lo, lb, lc) + km(lb, lc, ay[2], ay[3]) - km(ax[2], ax[3], ay[2], ay[3])
            if s < score:
                best, score = (x, y), s
        if best and score < 900:
            if origin is None:
                a = airports[best[0]]
                t1 -= km(a[2], a[3], la, lo) / KM_PER_MIN * 60 + 300
            if dest is None:
                b = airports[best[1]]
                t2 += km(lb, lc, b[2], b[3]) / KM_PER_MIN * 60 + 300
            origin, dest = best
    if origin is None or dest is None:
        return None
    a, b = airports[origin], airports[dest]
    dist = km(a[2], a[3], b[2], b[3])
    if dist < MIN_KM:
        return None
    # 지상 신호가 끊겨 앞뒤 편이 한 편으로 묶이면 시간이 말이 안 된다.
    hours = (t2 - t1) / 3600
    if hours < dist / 1150 or hours > dist / 550 + 1.5:
        return None
    return (kind, call, int(t1), int(t2), origin, dest, track, observed)


def number_of(call, airlines):
    iata = airlines.get(call[:3])
    return f'{iata or call[:3]} {call[3:].lstrip("0") or "0"}'


def main():
    folder, day, out_dir = sys.argv[1:4]
    limit = int(sys.argv[4]) if len(sys.argv) > 4 else 0
    start = time.time()
    airports = load_airports()
    by_icao = {a[1]: i for i, a in enumerate(airports)}
    routes, airlines = load_routes(by_icao)
    print('노선', len(routes), '항공사', len(airlines), flush=True)
    paths = sorted(os.path.join(folder, f) for f in os.listdir(folder) if '.tar.' in f)
    raw, done = [], 0
    with ProcessPoolExecutor(os.cpu_count(), initializer=init_worker) as pool:
        pending = collections.deque()
        for batch in batches(paths, 200, limit):
            pending.append(pool.submit(work, batch))
            done += len(batch)
            while len(pending) > os.cpu_count() * 3:
                raw.extend(pending.popleft().result())
            if done % 4000 == 0:
                print(done, '기', len(raw), '구간', int(time.time() - start), '초', flush=True)
        for job in pending:
            raw.extend(job.result())
    legs = [leg for leg in (fill(r, routes, airports) for r in raw) if leg]
    both = sum(1 for leg in legs if leg[7])
    # 같은 편이 겹치면 하나만
    seen, unique = {}, []
    for leg in sorted(legs, key=lambda x: (not x[7], x[2])):
        key = (leg[1], leg[4], leg[2] // 2400)
        if key in seen:
            continue
        seen[key] = True
        unique.append(leg)
    dep = collections.defaultdict(list)
    arr = collections.defaultdict(list)
    tracks = collections.defaultdict(dict)
    for kind, call, t1, t2, origin, dest, track, observed in unique:
        no = number_of(call, airlines)
        a, b = airports[origin][0], airports[dest][0]
        dep[a].append([t1, t2, no, b, kind, 1 if observed else 0])
        arr[b].append([t2, t1, no, a, kind, 1 if observed else 0])
        tracks[a][f'{no}|{t1}'] = track
    base = os.path.join(out_dir, day)
    os.makedirs(os.path.join(base, 't'), exist_ok=True)
    size = 0
    for a in airports:
        code = a[0]
        if code not in dep and code not in arr:
            continue
        path = os.path.join(base, f'{code}.json')
        with open(path, 'w', encoding='utf8') as f:
            json.dump({'dep': sorted(dep.get(code, [])), 'arr': sorted(arr.get(code, []))}, f, separators=(',', ':'))
        size += os.path.getsize(path)
        if code in tracks:
            path = os.path.join(base, 't', f'{code}.json')
            with open(path, 'w', encoding='utf8') as f:
                json.dump(tracks[code], f, separators=(',', ':'))
            size += os.path.getsize(path)
    count = sorted((len(dep.get(a[0], [])) for a in airports), reverse=True)
    summary = {
        'day': day,
        'aircraft': done,
        'segments': len(raw),
        'flights': len(unique),
        'observed_both_ends': both,
        'airports_ge_1': sum(c >= 1 for c in count),
        'airports_ge_6': sum(c >= 6 for c in count),
        'airports_ge_24': sum(c >= 24 for c in count),
        'airports_ge_100': sum(c >= 100 for c in count),
        'median_departures': count[len(count) // 2],
        'sample': {c: len(dep.get(c, [])) for c in ['ICN', 'GMP', 'CJU', 'NRT', 'HND', 'PEK', 'PVG', 'CAN', 'HKG', 'SIN', 'BKK', 'DEL', 'DXB', 'IST', 'LHR', 'CDG', 'FRA', 'JFK', 'LAX', 'ATL', 'GRU', 'JNB', 'NBO', 'LOS', 'SYD', 'SVO']},
        'mb': round(size / 1048576, 1),
        'seconds': int(time.time() - start),
    }
    with open(os.path.join(base, '_summary.json'), 'w', encoding='utf8') as f:
        json.dump(summary, f, indent=1)
    print(json.dumps(summary).encode('ascii', 'replace').decode())


if __name__ == '__main__':
    main()
