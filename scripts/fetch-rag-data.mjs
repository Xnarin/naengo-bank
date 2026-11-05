// RAG 원천 데이터 수집: node scripts/fetch-rag-data.mjs
// 1) 법령: legalize-kr (국가법령정보센터 원문을 Markdown으로 미러링한 GitHub 저장소) — 키 불필요
// 2) 금융상품: 금감원 finlife Open API — FINLIFE_KEY 환경변수 필요 (https://finlife.fss.or.kr 에서 무료 발급)
import { mkdir, writeFile } from 'node:fs/promises';

const OUT = 'data/rag';
const LAWS = {
  예금자보호법: ['법률', '시행령'],
  금융소비자보호에관한법률: ['법률', '시행령'],
  전자금융거래법: ['법률', '시행령'],
  전기통신금융사기피해방지및피해금환급에관한특별법: ['법률'],
  금융실명거래및비밀보장에관한법률: ['법률', '시행령'],
};

async function get(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${url}`);
  return r.text();
}

await mkdir(`${OUT}/laws`, { recursive: true });
for (const [law, kinds] of Object.entries(LAWS)) {
  for (const k of kinds) {
    const md = await get(`https://raw.githubusercontent.com/legalize-kr/legalize-kr/main/kr/${encodeURIComponent(law)}/${encodeURIComponent(k)}.md`);
    await writeFile(`${OUT}/laws/${law}_${k}.md`, md);
    console.log('law', law, k, md.length);
  }
}

// finlife: 은행권(020000) 예금·적금·신용대출·전세대출·주담대
const key = process.env.FINLIFE_KEY;
if (!key) {
  console.log('FINLIFE_KEY 없음 → 금융상품 수집 건너뜀');
} else {
  await mkdir(`${OUT}/products`, { recursive: true });
  const APIS = ['depositProductsSearch', 'savingProductsSearch', 'creditLoanProductsSearch', 'rentHouseLoanProductsSearch', 'mortgageLoanProductsSearch'];
  for (const api of APIS) {
    const pages = [];
    for (let p = 1; ; p++) {
      const j = JSON.parse(await get(`https://finlife.fss.or.kr/finlifeapi/${api}.json?auth=${key}&topFinGrpNo=020000&pageNo=${p}`)).result;
      if (j.err_cd !== '000') throw new Error(`${api}: ${j.err_msg}`);
      pages.push(j);
      if (p >= Number(j.max_page_no)) break;
    }
    const merged = { baseList: pages.flatMap((x) => x.baseList), optionList: pages.flatMap((x) => x.optionList) };
    await writeFile(`${OUT}/products/${api}.json`, JSON.stringify(merged, null, 2));
    console.log('finlife', api, merged.baseList.length);
  }
}
