# 참고 자료 (RAG에 직접 넣지 않음)

내금고 자체 FAQ·약관·상품설명서를 **만들 때 참고**하는 다른 은행 자료입니다.
카카오뱅크 저작물이고 수치(한도, 금리 등)도 카카오뱅크 기준이라, 그대로 청크로 넣으면 챗봇이 "내금고"가 아닌 카카오뱅크 기준으로 답합니다.
구조·항목·문체만 참고해서 내금고 문서를 새로 쓰고, 그 문서를 `data/rag/`에 넣습니다.

## kakaobank/ (2026-11-05 수집)

| 파일 | 내용 | 원본 |
|---|---|---|
| `faq.jsonl` | 고객센터 FAQ 2,183건 (통장/저축 532, 대출 919, 카드 349, 인증/보안 119, 앱 이용 90, 알림 18, ATM 30, 기타 126). 카테고리가 겹쳐 id 중복 15건 | https://www.kakaobank.com/Help/Guide/Faq (공개 API `/api/v1/search/FAQ?tag=…&page=N`) |
| `입출금이자유로운예금약관.pdf` | 은행 공통 표준 약관 (카카오뱅크 게시본) | 상품공시실 → 카카오뱅크 입출금통장 |
| `적립식예금약관.pdf` | 은행 공통 표준 약관 (카카오뱅크 게시본) | 상품공시실 → 카카오뱅크 자유적금 |
| `전자금융거래기본약관.html` | 카카오뱅크 전자금융거래 기본약관 | https://www.kakaobank.com/Corp/Policy/EBanking |
| `자동이체송금약관.pdf` | 자동이체 약관 | 상품공시실 → 자유적금 |
| `입출금통장_상품설명서.pdf`, `입출금통장_특약.pdf` | 상품설명서 양식, 특약 | 상품공시실 → 입출금통장 |
| `자유적금_상품설명서.pdf`, `자유적금_특약.pdf` | 상품설명서 양식, 중도해지이율 등 | 상품공시실 → 자유적금 |

상품공시실: https://kakaobank.com/Help/Documents/ProductDeclaration/Products (상품 클릭 → 약관·설명서 PDF 링크)

## 표준약관 3종을 어디서 받나
- **은행연합회에는 원문이 따로 게시돼 있지 않습니다.** 소비자포털(portal.kfb.or.kr)과 협회 사이트(kfb.or.kr)의 법규·자율규제 메뉴를 확인했지만 없습니다.
- 입출금이자유로운예금약관, 적립식예금약관은 은행연합회가 만든 공통 약관이라 **각 은행 상품공시실**에 거의 같은 내용으로 올라와 있습니다. 위 카카오뱅크 PDF가 그것입니다.
- 전자금융거래기본약관은 공정위 표준약관(2001년 의결)을 바탕으로 은행마다 조금씩 다르게 씁니다. 위 카카오뱅크 HTML을 참고합니다.
- 예금거래기본약관과 은행여신거래기본약관은 공정위 표준약관으로 `data/rag/terms/`에 이미 있습니다.

## 은행연합회 소비자포털 (고객 안내문, 참고하거나 RAG 후보)
| 내용 | 링크 |
|---|---|
| 자주묻는질문(FAQ) | https://portal.kfb.or.kr/minwon/faq.php |
| 은행 이용 프로 되기 (은행 이용, 상품 가입, 소비자보호) | https://portal.kfb.or.kr/finedu/bank_pro0.php |
| 은행관련용어 | https://portal.kfb.or.kr/finedu/bank_term0.php |
| 보이스피싱 대응요령 / 피해 신고처 | https://portal.kfb.or.kr/voice/vphishing_correspond.php , https://portal.kfb.or.kr/voice/vphishing_report.php |
| 휴면예금조회 안내 | https://portal.kfb.or.kr/consumer/sleepmoney.php |
| 은행수수료에 대한 이해 / 예금수수료 비교 | https://portal.kfb.or.kr/compare/commission.php , https://portal.kfb.or.kr/compare/commission_deposit.php |
| 금융소비자의 주요 권리 안내 | https://portal.kfb.or.kr/minwon/financial_consumer_rights_notify.php |

이 사이트는 브라우저 외 요청을 막아서(오류 페이지 반환) 자동 수집하지 않았습니다. 필요한 페이지는 브라우저에서 열어 확인하세요.
