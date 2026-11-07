#!/bin/bash
# GitHub Actions 에서 돈다. 새 날짜 기록을 처리해 저장소 Release 에 묶음으로 두고, 필요한 날짜만 사이트에 넣는다.
set -uo pipefail

TAG=flights
SOURCE=adsblol/globe_history_2026
gh release view "$TAG" >/dev/null 2>&1 || gh release create "$TAG" --title "Flight records" --notes "Daily airport tables derived from ADSB.lol flight data. Offered under the Open Database License (ODbL 1.0)."
have=$(gh release view "$TAG" --json assets --jq '.assets[].name')

curl -fsSL -o harvest/standing.zip https://codeload.github.com/vradarserver/standing-data/zip/refs/heads/main
export MP_VRS="$PWD/harvest/standing.zip"

# 아직 처리하지 않은 날짜(최근 9일). 오늘 쓸 날짜부터 처리한다.
for back in 7 6 8 5 4 3 2 1 9; do
  day=$(date -u -d "-$back day" +%F)
  name="flights-$day.tar.gz"
  if grep -qx "$name" <<<"$have"; then continue; fi
  tag="v${day//-/.}-planes-readsb-prod-0"
  dir="work/$day"
  mkdir -p "$dir"
  if ! gh release download "$tag" -R "$SOURCE" -p '*.tar.*' -D "$dir"; then
    echo "$day 기록 없음, 건너뜀"
    rm -rf "$dir"
    continue
  fi
  python3 -I harvest/harvest_flights.py "$dir" "$day" out | tail -1 | cut -c1-200
  rm -f "out/$day/_summary.json"
  tar -czf "$name" -C out "$day"
  gh release upload "$TAG" "$name" --clobber
  rm -rf "$dir" "out/$day" "$name"
done

# 사이트 조립: 게임 파일 + 오늘 쓸 날짜의 표(7일 전 앞뒤)
mkdir -p _site/flights
cp -r index.html credits.html og.jpg assets lang ads _site/
# 문화재 자료는 저장소가 아니라 Release 묶음으로 둔다(사진 4천여 장).
if gh release download heritage -p 'heritage-site.tar.gz' -D dl --clobber; then
  mkdir -p _site/heritage
  tar -xzf dl/heritage-site.tar.gz -C _site/heritage
fi
for back in 9 8 7 6 5; do
  day=$(date -u -d "-$back day" +%F)
  name="flights-$day.tar.gz"
  if gh release download "$TAG" -p "$name" -D dl --clobber; then
    tar -xzf "dl/$name" -C _site/flights
  fi
done
du -sh _site

# 2주 넘은 묶음은 지운다
cutoff=$(date -u -d "-14 day" +%F)
for name in $(gh release view "$TAG" --json assets --jq '.assets[].name'); do
  day=${name#flights-}
  day=${day%.tar.gz}
  if [[ "$day" < "$cutoff" ]]; then gh release delete-asset "$TAG" "$name" -y; fi
done

# 저장소 변경이 60일 없으면 예약 실행이 꺼지므로 스스로 다시 켠다.
gh api -X PUT "repos/$GITHUB_REPOSITORY/actions/workflows/daily.yml/enable" || true
exit 0
