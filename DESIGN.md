---
name: 내금고
description: 나만 여는 금고. AI 금융 어시스턴트를 결합한 모바일 인터넷뱅킹 프로토타입
colors:
  violet: "#5b4bdb"
  violet-deep: "#4636c4"
  violet-wash: "#eeecfb"
  midnight-ink: "#1c1a2e"
  drawer-1: "#efedfc"
  drawer-2: "#f2f1f6"
  drawer-3: "#f9eff3"
  drawer-4: "#ecf3f8"
  white: "#ffffff"
  mist: "#f5f4f9"
  rule-line: "#e8e6f0"
  dusk-gray: "#5c5a6e"
  faded-dusk: "#a3a1b3"
  backdrop: "#e9e7f1"
  money-green: "#15803d"
  money-wash: "#eaf6ee"
  error-red: "#c8283a"
  error-wash: "#fbe9e7"
typography:
  amount-input:
    fontFamily: "Sora, Wanted Sans Variable, sans-serif"
    fontSize: "34px"
    fontWeight: 700
    letterSpacing: "-0.02em"
    fontFeature: "\"tnum\""
  amount-hero:
    fontFamily: "Sora, Wanted Sans Variable, sans-serif"
    fontSize: "30px"
    fontWeight: 700
    letterSpacing: "-0.02em"
    fontFeature: "\"tnum\""
  page-heading:
    fontFamily: "Sora, Wanted Sans Variable, sans-serif"
    fontSize: "24px"
    fontWeight: 700
  headline:
    fontFamily: "Sora, Wanted Sans Variable, sans-serif"
    fontSize: "22px"
    fontWeight: 700
    lineHeight: 1.375
  amount-inline:
    fontFamily: "Sora, Wanted Sans Variable, sans-serif"
    fontSize: "20px"
    fontWeight: 700
    letterSpacing: "-0.02em"
    fontFeature: "\"tnum\""
  title:
    fontFamily: "Sora, Wanted Sans Variable, sans-serif"
    fontSize: "18px"
    fontWeight: 700
  bar-title:
    fontFamily: "Wanted Sans Variable, -apple-system, system-ui, sans-serif"
    fontSize: "17px"
    fontWeight: 600
  input:
    fontFamily: "Wanted Sans Variable, -apple-system, system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 400
  body:
    fontFamily: "Wanted Sans Variable, -apple-system, system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.5
    letterSpacing: "-0.01em"
  body-small:
    fontFamily: "Wanted Sans Variable, -apple-system, system-ui, sans-serif"
    fontSize: "14px"
    fontWeight: 400
  label:
    fontFamily: "Wanted Sans Variable, -apple-system, system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 500
  caption:
    fontFamily: "Wanted Sans Variable, -apple-system, system-ui, sans-serif"
    fontSize: "12px"
    fontWeight: 400
  micro:
    fontFamily: "Wanted Sans Variable, -apple-system, system-ui, sans-serif"
    fontSize: "11px"
    fontWeight: 500
rounded:
  md: "12px"
  lg: "16px"
  drawer: "22px"
  drawer-head: "20px"
  sheet: "24px"
  pill: "9999px"
spacing:
  gutter: "20px"
  tile-gap: "10px"
  row: "16px"
  section: "32px"
components:
  button-primary:
    backgroundColor: "{colors.violet}"
    textColor: "{colors.white}"
    rounded: "{rounded.pill}"
    height: "44px"
    padding: "0 20px"
  button-primary-hover:
    backgroundColor: "{colors.violet-deep}"
  button-primary-lg:
    backgroundColor: "{colors.violet}"
    textColor: "{colors.white}"
    rounded: "{rounded.pill}"
    height: "56px"
  button-secondary:
    backgroundColor: "{colors.mist}"
    textColor: "{colors.midnight-ink}"
    rounded: "{rounded.pill}"
    height: "44px"
  button-outline:
    backgroundColor: "{colors.white}"
    textColor: "{colors.midnight-ink}"
    rounded: "{rounded.pill}"
    height: "36px"
  input-field:
    backgroundColor: "{colors.white}"
    textColor: "{colors.midnight-ink}"
    rounded: "{rounded.md}"
    height: "52px"
    padding: "0 16px"
  drawer-tile:
    backgroundColor: "{colors.drawer-1}"
    textColor: "{colors.midnight-ink}"
    rounded: "{rounded.drawer}"
    padding: "16px"
  chip-suggestion:
    backgroundColor: "{colors.white}"
    textColor: "{colors.midnight-ink}"
    rounded: "{rounded.pill}"
    padding: "8px 14px"
  chat-bubble-user:
    backgroundColor: "{colors.violet}"
    textColor: "{colors.white}"
    rounded: "{rounded.lg}"
    padding: "10px 16px"
  chat-bubble-assistant:
    backgroundColor: "{colors.mist}"
    textColor: "{colors.midnight-ink}"
    rounded: "{rounded.lg}"
    padding: "10px 16px"
---

# Design System: 내금고

## Overview

**Creative North Star: "서랍이 있는 금고"**

내금고(naengo)는 "나만 여는 금고"다. 계좌 하나하나는 금고의 서랍이고, 서랍마다 고유한 색이 있다. 홈에서는 서랍들이 겹쳐 쌓여 있고, 누른 서랍 하나만 스르륵 열려 잔액과 버튼을 보여 준다. 어느 돈이 어디 있는지 색만 보고도 안다. 연한 서랍 색이 순서대로 붙고, 그 서랍의 상세 화면도 같은 색 머리를 단다.

바탕은 흰색, 강조는 차분한 바이올렛 하나, 글자는 밤하늘색 잉크, 서랍은 아주 연한 파스텔이다. 색은 절제하고, 개성은 서랍 구조와 서체(원티드 산스 + Sora)에서 나온다. 강조색은 프로필의 색 테마로 바꿀 수 있다.

밀도는 은행 앱답게 촘촘하되 서랍 타일은 넉넉하게. 장식은 서랍 색과 체크카드에만 쓰고, 목록·폼·확인 화면은 흰 위에 얇은 선으로 차분하게 정리한다.

**Key Characteristics:**
- 흰 바탕, 바이올렛 강조, 밤하늘색 잉크 글자. 색 테마로 모노·틸·코랄 전환.
- 계좌 = 색 서랍. 가로로 긴 서랍이 겹쳐 쌓이고, 한 번에 하나만 열린다.
- 주요 버튼은 강조색 바탕 + 흰 글자의 알약형.
- 입금과 완료는 리프 그린, 출금은 미드나잇 잉크 그대로.
- 금액 숫자와 제목은 Sora, 한글은 원티드 산스. Pretendard는 쓰지 않는다.

## Colors

기본은 **바이올렛**: 흰 바탕, 차분한 보라 강조 하나, 밤하늘색 잉크 글자, 아주 연한 서랍 색(라벤더, 안개 회색, 블러시, 아이스). 보라는 채도를 낮춰 장난스럽지 않게, 금고의 단단함과 앱의 산뜻함 사이에 둔다.

프로필 → 색 테마에서 **모노, 틸, 코랄**로 바꿀 수 있다. 테마는 `<html data-theme>`가 같은 이름의 CSS 변수(`--color-brand`, `--color-drawer-1..4`, `--color-mark-1..4` 등)를 덮어쓰는 방식이라, 컴포넌트는 테마를 몰라도 된다. 아래 값은 기본(바이올렛) 기준이다.

### Primary
- **Violet** (violet): 주요 버튼 바탕(흰 글자, 대비 6:1), 서랍의 "송금" 버튼, 활성 탭, 금리 숫자, 사용자 말풍선, 로고 바탕, 포커스 외곽선.
- **Violet Deep** (violet-deep): 보라 버튼의 hover·active.
- **Violet Wash** (violet-wash): 활성 탭 아이콘 뒤 알약, 선택된 출금 계좌 배경.

### Secondary
- **Midnight Ink** (midnight-ink): 본문 글자, 합계 금액, 선택된 기간 필터 칩, 계좌번호 "확인" 버튼.

### Tertiary
- **Drawer 1–4** (drawer-1 ~ drawer-4): 첫 번째부터 네 번째 서랍 바탕(라벤더, 안개 회색, 블러시, 아이스). 목록에서 같은 계좌를 가리킬 때는 이 색 대신 진한 표시색 막대(보라 #5B4BDB, 회보라 #8A879C, 로즈 #C0708F, 스틸블루 #5C8FB3)를 쓴다.

### Neutral
- **White** (white): 앱 바탕, 상단 바, 하단 탭, 입력, 테두리 묶음.
- **Mist** (mist): 확인 상자, 보조 버튼, 어시스턴트 말풍선, 스켈레톤.
- **Rule Line** (rule-line): 입력 테두리, 구분선, 아웃라인 버튼.
- **Dusk Gray** (dusk-gray): 보조 문구, 라벨, 날짜, 비활성 탭. 읽어야 하는 회색 글자는 모두 이 색이다.
- **Faded Dusk** (faded-dusk): 꺾쇠·빈 상태 아이콘 등 읽지 않아도 되는 요소에만.
- **Backdrop** (backdrop): 데스크톱에서 앱 바깥 배경.

### Status
- **Money Green / Money Wash**: 입금(+) 금액, 사용 가능 확인, 송금 완료, "사용 중" 카드.
- **Error Red / Error Wash**: 입력 오류, 송금 실패, 잔액 초과, 정지 카드.

### Named Rules
**The One Accent Rule.** 강조색은 테마의 `--color-brand` 하나다. 컴포넌트에 색 hex를 직접 쓰지 않고 토큰만 쓴다(체크카드의 샌드 테마와 금색 칩만 예외). 보라에 핑크·파랑 그라데이션을 섞은 "AI 보라"는 쓰지 않는다.

**The Key Button Rule.** 채운 강조 버튼은 화면의 주요 실행(또는 서랍마다의 "송금")에만 쓴다. 나머지는 미스트 면이나 테두리 버튼이다.

**The Drawer Color Rule.** 서랍 색은 계좌 순서로 정해지고 화면이 바뀌어도 같다. 연한 서랍 색은 면(홈 서랍, 계좌 상세 머리, 송금의 출금 계좌 아이콘)에, 같은 순서의 진한 표시색은 목록 막대에 쓴다.

**The Readable Gray Rule.** 읽어야 하는 글자는 Dusk Gray 이상(흰 바탕 대비 6.5:1). Faded Dusk는 글자에 쓰지 않는다.

## Typography

**Display Font:** Sora (600, 700; with Wanted Sans Variable)
**Body Font:** Wanted Sans Variable 원티드 산스 (400–1000; with -apple-system, system-ui)

**Character:** 한글은 모두 원티드 산스. 기하학적이고 단정한 최신 고딕이라 흔한 기본 서체와 결이 다르다. 금액 숫자와 제목 속 라틴 글자는 Sora로, 둥글고 넓은 숫자가 금액을 친근하고 또렷하게 만든다(Sora에 없는 한글 "원"은 원티드 산스로 자연스럽게 이어진다). 두 서체 모두 OFL이며 npm(`wanted-sans`, `@fontsource/sora`)으로 프로젝트에 포함한다.

### Hierarchy
- **Amount Input** (Sora 700, 34px, tabular): 송금 금액 입력.
- **Amount Hero** (Sora 700, 30px, tabular): 전체 잔액, 계좌 상세 잔액, 카드 월 합계, 거래 상세 금액.
- **Page Heading** (Sora 700, 24px): 로그인 제목, 상품 상세의 상품명.
- **Headline** (Sora 700, 22px, 1.375): 단계 질문, 완료 메시지.
- **Amount Inline** (Sora 700, 17–20px, tabular): 닫힌 서랍 잔액(17px), 열린 서랍 잔액(30px), 챗봇 카드 합계(20px), 새 계좌번호.
- **Title** (Sora 700, 17–18px): 모든 h1·h2(상단 바 제목, 섹션 제목, 시트 제목)와 로고 워드마크. 상품 카드 이름은 본문 서체.
- **Input** (400, 16px): 입력 글자.
- **Body** (400–600, 15px, 1.5): 목록 행, 말풍선, 버튼, 서랍 이름.
- **Body Small** (400–600, 14px): 작은 버튼, 칩, 오류 문구.
- **Label** (500, 13px): 입력 라벨, 날짜 그룹, 서랍 안 버튼.
- **Caption** (400, 12px): 예시 데이터 각주, 계좌번호, 거래 후 잔액.
- **Micro** (500, 11px): 하단 탭 이름, 진행 단계 이름, 카드 위 CHECK.

### Named Rules
**The Tabular Money Rule.** 금액과 계좌번호는 항상 `.num`(tabular-nums, -0.02em). 20px 이상 금액은 Sora, 그보다 작은 금액과 계좌번호는 원티드 산스. 금액은 천 단위 쉼표와 "원"을 붙인다.

**The Two Voices Rule.** Sora는 금액과 제목(h1·h2)에만 쓴다. 버튼, 라벨, 입력, 목록 본문은 원티드 산스.

**The No Eyebrow Rule.** 제목 위에 작은 라벨이나 태그를 얹지 않는다. 상품 태그는 제목 오른쪽에 붙인다.

## Layout

- 단일 컬럼, 최대 폭 430px, 좌우 여백 20px. 데스크톱에서는 Counter 색 위 가운데에 놓인다.
- 홈: 인사(작게) → "금고 N개에 보관 중" + 합계 → 서랍 스택 → 최근 거래 → 바로가기 목록.
- 서랍 스택은 전체 폭, 서랍끼리 24px 겹친다. 처음에는 첫 서랍이 열려 있다.
- 상단 바 56px(sticky), 하단 탭 64px(fixed). 송금·계좌 개설·상품 상세는 하단 탭을 숨기고 주요 버튼을 하단에 고정한다.
- 섹션 사이 32px, 섹션 제목 아래 12px.

## Elevation & Depth

평면이다. 깊이는 흰, 미스트, 서랍 색 사이의 명도와 색 차이로 만든다. 그림자는 체크카드와 데스크톱의 앱 경계에만 있다. 하단 시트는 반투명 검정 배경으로 앞에 있음을 보여 준다.

### Shadow Vocabulary
- **Card Object** (`box-shadow: 0 10px 30px rgba(14,30,74,0.18)`): 체크카드 이미지 전용.
- **App Frame** (`box-shadow: 0 0 40px rgba(14,30,74,0.08)`): 데스크톱 앱 경계.

### Named Rules
**The Flat Drawer Rule.** 서랍, 목록, 버튼, 입력에는 그림자를 쓰지 않는다. 색 면 자체가 구분이다.

## Shapes

서랍은 22px, 계좌 상세 머리는 20px, 목록 묶음과 결과 상자는 16px, 입력은 12px, 하단 시트 위쪽은 24px. 버튼, 칩, 필터, 아이콘 원은 알약형. 선택 상태는 2px 강조색 테두리.

## Components

### Buttons
- **Shape:** 모두 알약형. 높이 sm 36px, md 44px, lg 56px.
- **Primary:** 강조색 바탕 + 흰 글자, semibold. 로딩 중 회전 아이콘.
- **Hover / Focus:** hover 색으로 바뀐다. 키보드 포커스는 2px 강조색 외곽선.
- **Secondary:** 미스트 바탕 + 미드나잇 잉크 글자.
- **Outline:** 흰 바탕 + Rule Line 테두리.
- **Disabled:** 같은 버튼을 35% 불투명도로.

### Drawer Stack
계좌를 금고 서랍으로 보여 주는 홈의 핵심 컴포넌트. 서랍은 전체 폭, 서랍 색 바탕, 22px 라운드이고 아래 서랍이 위 서랍의 아랫부분을 24px 덮으며 쌓인다. 맨 위 가운데에 서랍 손잡이(36×4px, 미드나잇 잉크 15%).
- **닫힌 서랍:** 한 줄. 왼쪽 상품명(브랜드 접두어 생략), 오른쪽 Sora 17px 잔액. 줄 전체가 여닫는 버튼(aria-expanded).
- **열린 서랍:** 계좌번호(12px, 미드나잇 잉크 65%), Sora 30px 잔액, 맨 아래 왼쪽 "거래내역 ›" 텍스트 버튼과 오른쪽 "송금 ↗" 알약(강조색 + 흰 글자, 36px). 머리 줄의 작은 잔액은 사라진다.
- **움직임:** 한 번에 하나만 열린다. 열림은 grid-template-rows 0fr→1fr, 300ms ease-out. 동작 줄이기 설정에서는 즉시 바뀐다.

### Chips
- **필터 칩(기간):** 선택 시 미드나잇 잉크 바탕 + 흰 글자, 비선택은 미스트 + Dusk Gray.
- **추천 질문·선택지 칩:** 흰 바탕, 옅은 미드나잇 잉크 테두리, 미드나잇 잉크 글자.
- **구분 탭(전체/입금/출금):** 선택 시 미드나잇 잉크 2px 밑줄.

### Cards / Containers
- **확인 상자:** 미스트 바탕에 라벨–값 행.
- **테두리 묶음:** 흰 바탕 + Rule Line 테두리, 16px. 최근 거래, 상품 카드, 챗봇 응답 카드.
- **계좌 상세 머리:** 그 계좌의 서랍 색 상자(20px)에 계좌번호, 잔액, 송금 버튼.

### Inputs / Fields
- **Style:** 흰 바탕, 1px Rule Line, 12px, 높이 52px, 16px 글자.
- **Focus:** 테두리가 미드나잇 잉크로. 입력 커서도 미드나잇 잉크.
- **Error:** 테두리 Error Red와 아래 오류 문구. 성공 확인은 Money Green 문구.

### Navigation
- **하단 탭:** 홈 / 상품 / 카드 / AI. 아이콘 22px + 11px 라벨. 활성은 강조색과 아이콘 뒤 Violet Wash 알약(48×28px), 비활성은 Dusk Gray.
- **상단 바:** 뒤로가기 + 화면 제목 + 우측 동작, 흰 반투명 바탕.

### Ledger Rows
상품 목록, 거래내역, 최근 거래는 카드가 아니라 구분선으로 나뉜 줄(장부 행)이다.
- **상품 행:** 왼쪽에 상품명(브랜드 접두어 생략)과 옆의 작은 태그 글자, 한 줄 소개, 혜택 두 개를 " · "로 이은 줄. 오른쪽에 "최고 연" 라벨, Sora 22px 금리, "기본 n%". 목록 위는 "입출금통장 N" 개수와 글자 정렬 버튼(추천순 / 금리순, 선택은 굵게), 목록 끝에 예시 데이터 각주.
- **거래 행:** 아이콘 원 없이 상대방, 시간·메모, 오른쪽 금액(입금 Money Green)과 거래 후 잔액. 여러 계좌가 섞이는 곳(홈 최근 거래)에서는 왼쪽에 그 계좌의 서랍 색 세로 막대(6×32px)를 붙인다.
- **카드 메타 줄:** 카드 이미지 아래 한 줄. 카드 이름 + 상태 점과 글자(사용 중 Money Green / 분실 정지 Error Red), 그 아래 "•••• 끝자리 · 서랍 색 막대 + 연결 계좌 이름", 오른쪽 "사용내역 ›" 테두리 버튼.

### Logo
강조색 라운드 사각형 안에 흰 원(금고 다이얼), 가운데 강조색 점과 위쪽 눈금. 옆에 "내금고" 워드마크, 로그인에서는 "나만 여는 금고" 태그라인.

### Check Card
1.586 비율, 16px 라운드, 테마 세 가지: 네이비→강조색 그라데이션(흰 글자), 연한 서랍색 그라데이션(잉크 글자), 샌드 그라데이션(잉크 글자). 앞의 두 가지는 테마를 따른다. "NAENGO" 워드마크, 금색 칩, "•••• 마지막 4자리". 정지 카드는 반투명 검정 덮개.

### PIN Sheet
- 송금 직전 바텀시트(송금 화면, AI 송금 확인 카드 공통). 6개 점은 입력되면 바이올렛으로 채워지고, 틀리면 흔들리며 빨간 안내와 횟수(n/5)가 나온다(prefers-reduced-motion이면 흔들림 없음). 5회 틀리면 잠기고 데모 초기화로 풀린다.
- 키패드는 열 때마다 숫자를 섞는다. 숫자는 Sora 24px이고 배경 없이 눌렀을 때만 surface가 깔린다. 예시 비밀번호는 안내 줄에 표시한다.

### Notifications
- 홈 헤더의 종 아이콘. 안 읽은 알림이 있으면 바이올렛 숫자 배지(9+까지).
- 알림 화면은 날짜별 Ledger Rows. 줄 위의 작은 라벨이 종류를 말한다(입금 success, 예약 송금 brand, 예약 실패 danger). 새 알림은 왼쪽 바이올렛 점과 굵은 제목으로 구분하고, 아이콘 원은 쓰지 않는다.
- 맨 위 "보낼 예정 n건"에는 대기 중인 예약 송금이 놓이고, 각 줄에 취소 버튼(outline pill)이 있다.

### Account Management
- 계좌 상세의 "관리" 버튼으로 들어간다. 항목은 줄로 나뉜 한 화면이다: 즐겨찾기(별, 켜면 바이올렛으로 채움), 계좌 상태(정상 success 점 / 거래중지 danger 점), 이체한도(오늘·이번 달 사용액 / 한도, 얇은 막대. 90% 이상이면 danger), 계좌 해지(danger 글자 줄).
- 거래중지는 서랍 이름 옆 빨간 "거래중지" 글자로 알리고, 서랍의 송금 버튼은 navy "해제하기"로 바뀐다.
- 해지 화면은 조건 4줄의 점검표다. 줄마다 통과(success 체크) 또는 확인 필요(danger)와 해결 링크(brand 글자)가 붙는다. 해지 버튼은 navy를 쓴다. 되돌릴 수 없는 일이라 바이올렛 강조를 쓰지 않는다.

### Auth & Account Settings
- 로그인은 두 얼굴이다. 처음이면 이메일 폼, 이 기기에서 로그인한 적이 있으면 "{이름}님, 간편비밀번호를 눌러 주세요"(이름은 바이올렛)와 PinPad. 아래에 "이메일로 로그인 · 다른 계정으로 로그인" 텍스트 링크.
- 회원가입은 Steps 4단계(약관 동의 / 이메일 인증 / 비밀번호 / 간편비밀번호). 간편비밀번호 단계는 푸터 버튼 없이 PinPad만 둔다.
- EmailVerify: 이메일 입력 + "인증번호 받기"(secondary) → 아래로 인증번호 칸이 rise로 나타나고 hint에 예시 코드를 보여 준다. 마치면 success 체크 hint.
- 계정 관리는 내 정보 / 보안 / 자동 로그아웃 / 회원 탈퇴 순서의 줄 목록. 바꾸는 일은 모두 바텀시트에서 한다. 자동 로그아웃은 송금 시점 토글과 같은 세그먼트 컨트롤이다. 회원 탈퇴는 계좌 해지처럼 danger 글자 줄과 navy 확인 버튼을 쓴다.

### Card Detail
- 카드에 들어가면 사용내역이 먼저다. 맨 위에 작은 카드 그림 + 번호·연결 계좌·상태(점 + 글자: 사용 중 success, 일시정지 sub, 분실 신고 danger)를 한 줄로 두고, 바로 아래 월별 사용내역이 온다.
- 관리 기능은 헤더 오른쪽 "관리"(설정 아이콘 + 글자) 버튼으로 여는 "카드 관리" 시트에 모은다: 행동 버튼 3칸(surface 바탕, 분실 신고만 danger 글자) → 1일 사용한도 Meter → 해외결제·결제 알림 토글 → "가상 결제 해 보기 · 체험용" → 카드 해지(danger 글자 줄). 시트 안에서 연 하위 시트(한도·분실 신고·해지·가상 결제)를 닫으면 카드 관리 시트로 돌아온다.
- 카드가 사용 중이 아니면 카드 그림 위에 반투명 검정 막과 상태 이름을 얹는다.
- 되돌릴 수 없는 일(분실 신고, 해지)은 설명이 담긴 확인 시트 → 간편비밀번호 두 단계를 거친다. 확인 버튼은 navy를 쓴다.
- 발급은 Steps 3단계(연결 계좌 / 설정 / 확인). 디자인 선택은 작은 카드 미리보기 3개다.

### Transaction Filters & Auto-transfer
- 거래내역 상단 고정 영역: 기간 pill 줄 + 오른쪽 둥근 아이콘 버튼 2개(검색, 받기). 검색 조건이 걸려 있으면 검색 버튼이 바이올렛으로 차고, 아래에 brand-soft 바탕 조건 칩(지우기 X)이 붙는다. 정렬은 건수 옆 작은 텍스트 버튼(최신순/오래된순)이다.
- 검색·받기는 바텀시트. 금액 범위는 두 칸 입력, 거래 유형은 navy pill 라디오.
- 받는 계좌 고르기(RecipientPicker): "내 계좌" 칩 줄, 그 아래 "최근·자주 보낸 계좌" 줄 목록(이름, 가린 계좌번호, n번 보냄, 오른쪽 별). 즐겨찾기 별은 바이올렛으로 채운다.
- 자동이체 목록은 Ledger Rows. 받는 분과 금액(Sora)이 한 줄, 주기·출금 계좌가 sub 줄, "다음 이체" 시각을 굵게, 직전 결과는 success/danger 아이콘 줄. 등록 버튼은 하단 고정 brand pill.

### Chat
사용자 말풍선은 오른쪽 강조색 + 흰 글자, 어시스턴트는 왼쪽 미스트. 응답은 말풍선 아래 카드와 칩·이동 버튼으로 이어진다. 첫 인사도 일반 메시지다. 에이전트 답변의 "- " 줄은 점 목록으로, 빈 줄은 문단으로 보여 준다.

### Insight Cards (챗봇 그래프)
- 소비 분석·잔액 예측·정기결제 후보 세 카드는 한 틀을 쓴다: 머리줄(무엇, 오른쪽에 기간·개수 sub 글자) → 답이 되는 숫자 하나(Sora 30px, 음수면 danger) → 한 줄 설명 → 그래프 → 장부 줄 → "계산 기준" 접기. 테두리 1px + rounded-2xl, 그림자·그라데이션·아이콘 타일 없음.
- 그래프 카드는 아바타 들여쓰기를 벗어나 대화 폭을 다 쓴다.
- 색은 강조색 하나를 농도(100·72·52·38·27·18%, color-mix)로만 나눈다. 테마를 바꾸면 그래프도 따라 바뀐다. 이전 기간처럼 비교 대상은 mute 회색.
- 소비 분석: SVG 도넛(조각 사이 틈, 고른 조각만 두껍게, 가운데 항목·%·금액) + 순위 장부 줄(색 막대, %, 금액). 비교 보기는 항목마다 이번(강조색)·지난(회색) 막대 두 줄과 증감(↗ danger 더 / ↘ success 덜).
- 잔액 예측: 옅은 면을 깐 선 그래프, 0원 아래는 danger 옅은 면과 점선, 예정 이체일은 속 빈 점. 그래프 전체가 투명한 range 입력이라 좌우로 밀거나 화살표 키로 날짜를 고른다. 고른 날짜의 잔액이 그래프 위에 Sora로 뜬다.
- 정기결제 후보: 월 합계 + 연 환산, 서비스별 몫을 나눈 가로 띠 하나, 그 아래 서비스 장부 줄(색 막대, 결제일, 횟수, 금액, 최근 날짜).
- 가장 작은 글자는 12px.

## Do's and Don'ts

### Do:
- **Do** 계좌를 겹쳐 쌓인 색 서랍으로 보여 주고, 같은 계좌는 모든 화면에서 같은 서랍 색을 쓴다.
- **Do** 주요 실행은 강조색 + 흰 글자 알약 버튼 하나로.
- **Do** 금액을 화면에서 가장 큰 글자로, tabular 숫자와 "원"으로 쓴다.
- **Do** 입금과 완료는 Money Green, 출금은 미드나잇 잉크으로 구분한다.
- **Do** 예시 금리와 가상 데이터는 목록 끝 각주나 메타 줄의 "예시 금리" 같은 조용한 문구로 밝힌다. 색 배지로 강조하지 않는다.
- **Do** 로딩은 스켈레톤, 실패는 원인과 다시 시도 버튼, 빈 상태는 다음 행동 문구로.

### Don't:
- **Don't** 쨍한 원색이나 두 번째 강조색을 들이지 않는다. 파란색 계열도 쓰지 않는다.
- **Don't** Pretendard 등 흔한 기본 서체로 되돌리지 않는다. 명조 계열은 예스러워 보여서 쓰지 않는다.
- **Don't** 서랍 색을 경고·성공 같은 상태 의미로 쓰지 않는다.
- **Don't** 계좌를 같은 크기 박스 타일 격자로 늘어놓지 않는다. 목록 항목을 테두리 카드로 감싸지 않는다(장부 행 사용). 라벨–값 상자로 이미 보이는 정보를 반복하지 않는다. 목록 행에 아이콘 원을 붙이지 않는다. 세그먼트 토글 대신 글자 정렬 버튼을 쓴다. 짙은 대형 요약 카드, 아이콘 타일, 제목 위 eyebrow 라벨도 쓰지 않는다.
- **Don't** AI 기능에 반짝이(✨) 아이콘을 쓰지 않는다.
- **Don't** 실존 은행의 이름, 로고, 카드 디자인을 가져오지 않는다.
