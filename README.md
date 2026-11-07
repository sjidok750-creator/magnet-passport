# Magnet Passport

전 세계 공항을 실제 시간으로 여행하고, 공항마다 활주로 모양 마그네틱을 모으는 웹 게임입니다.

**플레이:** https://sjidok750-creator.github.io/magnet-passport/

항공편은 지난주 같은 요일의 실제 비행 기록을 오늘 시각으로 옮긴 것입니다. 오늘의 실제 운항 정보가 아니므로 여행 계획에 쓰면 안 됩니다. 이 게임은 어떤 항공사·공항과도 관계가 없습니다.

이 저장소에는 배포용 파일과 항공편 표 생성 도구만 있습니다.

- `harvest/`: [ADSB.lol](https://github.com/adsblol/globe_history_2026) 비행 기록에서 공항별 표를 만드는 도구. 매일 GitHub Actions 로 돕니다.
- 생성한 표는 [Releases](../../releases/tag/flights) 에 있으며 ODbL 1.0 으로 제공합니다.
- 문화재 사진·설명 묶음은 [Releases](../../releases/tag/heritage) 의 `heritage-site.tar.gz` 에 있고 배포할 때 사이트에 풀립니다. 설명 글은 위키백과 발췌(CC BY-SA 4.0), 사진은 위키미디어 공용(사진별 조건)입니다.
- 광고판 설정은 `ads/ads.json` 입니다. 팔린 광고를 여기에 넣으면 다시 빌드하지 않아도 나옵니다.
- 자료·글꼴 출처는 [credits.html](credits.html) 에 있습니다.
