import { useEffect, useRef, useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowRight, Bot, CircleAlert, CircleCheck, RotateCcw, SendHorizontal } from 'lucide-react';
import { Button, Page, Row } from '../components/ui';
import { PinSheet } from '../components/bank';
import { chatClient, lookupAgentSchedule, lookupAgentTransfer, type Block, type ChatMessage } from '../api/chat';
import { BankError, captureSession } from '../api/http';
const SUGGESTIONS = ['내 계좌 잔액 알려줘', '지난달 소비 패턴 분석해줘', '내 소비패턴에 맞는 통장 추천해줘', '이번 달 돈이 부족할까?', '다음달 얼마 정도 쓸까?', '내 구독 중인 거 찾아줘', '송금하고 싶어'];
import { productById } from '../data/mock';
import { cn, fmtDateTime, fmtDay, signedWon, won } from '../lib/format';
import { useBank } from '../store';
import { InsightCard } from '../components/InsightCard';

const uid = () => Math.random().toString(36).slice(2);
/** 그래프 카드는 아바타 들여쓰기를 벗어나 대화 폭을 다 쓴다 */
const INSIGHT = new Set<Block['kind']>(['spendingInsight', 'forecastInsight', 'subscriptionInsight', 'recommendationInsight']);
type AgentConfirmation = Extract<Block, { kind: 'agentConfirm' }>;
type ConfirmationTarget = { msgId: string; idx: number; action: AgentConfirmation };

export function Assistant() {
  const bank = useBank();
  const { chat, setChat, user } = bank;
  const navigate = useNavigate();
  const [input, setInput] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const [pinFor, setPinFor] = useState<ConfirmationTarget | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const latestAnswerRef = useRef<HTMLDivElement>(null);
  const pending = chat.messages.some((m) => m.blocks?.some((b) => b.kind === 'agentConfirm' && b.status === 'pending'));
  useEffect(() => {
    const hasChart = chat.messages.at(-1)?.blocks?.some((block) => INSIGHT.has(block.kind));
    (hasChart ? latestAnswerRef.current : endRef.current)?.scrollIntoView({ behavior: 'smooth', block: hasChart ? 'start' : 'end' });
  }, [chat.messages.length, busy]);
  const push = (m: ChatMessage) => setChat((c) => ({ ...c, messages: [...c.messages, m] }));
  function setStatus(msgId: string, idx: number, status: AgentConfirmation['status']) {
    setChat((c) => ({ ...c, messages: c.messages.map((m) => m.id !== msgId ? m : { ...m,
      blocks: m.blocks?.map((b, i) => i === idx && b.kind === 'agentConfirm' ? { ...b, status } : b) }) }));
  }
  async function ask(text: string, addUser = true, label?: string) {
    const message = text.trim();
    if (!message || busyRef.current || pending) return;
    const sameSession = captureSession();
    busyRef.current = true; setBusy(true); setInput('');
    if (addUser) push({ id: uid(), role: 'user', text: label ?? message });
    try {
      const res = await chatClient.send({ message, context: chat.context, snapshot: {
        userName: user?.name ?? '', accounts: bank.myAccounts, txs: bank.db.txs, cards: bank.myCards,
        cardTxs: bank.db.cardTxs, recipients: [], scheduled: bank.db.scheduled, lookup: () => null, simulateError: false,
      } });
      setChat((c) => sameSession()
        ? { messages: [...c.messages, { id: uid(), role: 'assistant', blocks: res.blocks }], context: res.context }
        : c);
    } catch (e) {
      const error: ChatMessage = { id: uid(), role: 'assistant', retryText: message, blocks: [{ kind: 'text', text: (e as Error).message }] };
      setChat((c) => sameSession() ? { ...c, messages: [...c.messages, error] } : c);
    } finally { busyRef.current = false; setBusy(false); }
  }
  async function checkConfirmation({ msgId, idx, action }: ConfirmationTarget, sameSession: () => boolean) {
    const done = action.actionType === 'AUTO_TRANSFER'
      ? await lookupAgentSchedule(action.confirmationId).catch(() => false)
      : (await lookupAgentTransfer(action.confirmationId).catch(() => undefined))?.status === 'SUCCESS';
    if (!sameSession() || !done) return;
    setStatus(msgId, idx, 'done');
    await bank.refresh();
  }
  async function recheckConfirmation(target: ConfirmationTarget) {
    if (busyRef.current) return;
    busyRef.current = true; setBusy(true);
    try { await checkConfirmation(target, captureSession()); }
    finally { busyRef.current = false; setBusy(false); }
  }
  async function confirm(target: ConfirmationTarget, approved: boolean, pin?: string) {
    if (busyRef.current) return;
    const { msgId, idx, action } = target;
    const sameSession = captureSession();
    busyRef.current = true; setBusy(true); setStatus(msgId, idx, 'processing');
    try {
      const res = await chatClient.confirm(action.threadId, action.confirmationId, approved, pin);
      if (!sameSession()) return;
      setStatus(msgId, idx, res.status === 'failed' ? 'failed' : approved ? 'done' : 'cancelled');
      setChat((c) => sameSession()
        ? { messages: [...c.messages, { id: uid(), role: 'assistant', blocks: res.blocks }], context: res.context }
        : c);
      setPinFor(null);
      await bank.refresh();
    } catch (e) {
      if (!sameSession()) return;
      const uncertain = !(e instanceof BankError) || e.code === 'NETWORK' || e.code === 'NO_PENDING'
        || e.status === 408 || (e.status ?? 0) >= 500;
      if (approved && (action.actionType === 'TRANSFER' || action.actionType === 'AUTO_TRANSFER') && uncertain) {
        setStatus(msgId, idx, 'unknown');
        setPinFor(null);
        await checkConfirmation(target, sameSession);
        return;
      }
      if (e instanceof BankError && ['STALE_CONFIRMATION', 'NO_PENDING'].includes(e.code)) {
        setStatus(msgId, idx, 'failed');
        setPinFor(null);
        bank.toast(e.message);
        return;
      }
      setStatus(msgId, idx, 'pending');
      if (approved) throw e;
      bank.toast((e as Error).message);
    } finally { busyRef.current = false; setBusy(false); }
  }
  const submit = (e: FormEvent) => { e.preventDefault(); void ask(input); };
  const lastId = chat.messages.at(-1)?.id;
  return (
    <Page title="AI 은행 어시스턴트" nav right={<button disabled={busy} onClick={() => setChat({ messages: [], context: {} })} aria-label="새 대화" className="mr-1 grid size-10 place-items-center rounded-full text-sub"><RotateCcw className="size-5" /></button>}>
      <div className="flex gap-2 pt-4"><Avatar /><div className="min-w-0 flex-1 space-y-2">
        <p className={bubble}>{user?.name}님, 안녕하세요. 잔액·거래내역 조회, 소비 분석, 잔액 예측과 정기결제 후보 찾기를 도와드려요. 송금과 카드 변경은 내용을 확인하고 PIN을 입력해야 실행돼요.</p>
        <div className="flex flex-wrap gap-2">{SUGGESTIONS.map((s) => <button key={s} onClick={() => void ask(s)} disabled={busy || pending} className={chip}>{s}</button>)}</div>
      </div></div>
      <div className="space-y-4 pt-4" aria-live="polite">
        {chat.messages.map((m) => m.role === 'user'
          ? <div key={m.id} className="rise flex justify-end"><p className="max-w-[80%] rounded-2xl rounded-br-md bg-brand px-4 py-2.5 text-[15px] text-white">{m.text}</p></div>
          : <div key={m.id} ref={m.id === lastId ? latestAnswerRef : undefined} className="rise flex scroll-mt-20 gap-2"><Avatar /><div className="min-w-0 flex-1 space-y-2">
            {m.blocks?.map((b, i) => <div key={i} className={INSIGHT.has(b.kind) ? '-ml-10' : undefined}><BlockView b={b} active={m.id === lastId && !busy} onAsk={(s, label) => void ask(s, true, label)} onInput={() => inputRef.current?.focus()} onGo={(to) => navigate(to)}
              onConfirm={() => b.kind === 'agentConfirm' && setPinFor({ msgId: m.id, idx: i, action: b })}
              onCancel={() => { if (b.kind === 'agentConfirm') void confirm({ msgId: m.id, idx: i, action: b }, false); }}
              onCheckResult={() => { if (b.kind === 'agentConfirm') void recheckConfirmation({ msgId: m.id, idx: i, action: b }); }} /></div>)}
            {m.retryText && <Button size="sm" variant="secondary" disabled={busy || pending} onClick={() => { setChat((c) => ({ ...c, messages: c.messages.filter((x) => x.id !== m.id) })); void ask(m.retryText!, false); }}>다시 시도</Button>}
          </div></div>)}
        {busy && <div className="flex gap-2" aria-label="응답 작성 중"><Avatar /><span className="rounded-2xl bg-surface px-4 py-3 text-[14px] text-sub">처리하고 있어요…</span></div>}
        <div ref={endRef} className="h-28" />
      </div>
      <form onSubmit={submit} className="fixed bottom-16 left-1/2 z-30 flex w-full max-w-[430px] -translate-x-1/2 items-center gap-2 border-t border-line bg-paper px-4 py-2.5">
        <input ref={inputRef} value={input} maxLength={500} disabled={pending} onChange={(e) => setInput(e.target.value)} placeholder={pending ? '요청을 확인하거나 취소해 주세요' : '메시지를 입력하세요'} aria-label="메시지 입력" className="h-11 min-w-0 flex-1 rounded-full bg-surface px-4 text-[15px] outline-none focus:ring-2 focus:ring-brand/30" />
        <button type="submit" disabled={!input.trim() || busy || pending} aria-label="전송" className="grid size-11 shrink-0 place-items-center rounded-full bg-brand text-white disabled:bg-line"><SendHorizontal className="size-5" /></button>
      </form>
      <PinSheet open={!!pinFor} onClose={() => setPinFor(null)} purpose="요청을 실행하려면" onPass={async (pin) => { if (pinFor) await confirm(pinFor, true, pin); }} />
    </Page>
  );
}

// ── 응답 블록 렌더러 ──────────────────────────────────────
const bubble = 'w-fit max-w-full rounded-2xl rounded-tl-md bg-surface px-4 py-2.5 text-[15px] leading-relaxed';
const chip = 'rounded-full border border-brand/30 bg-paper px-3.5 py-2 text-[14px] font-medium text-brand hover:bg-brand-soft disabled:border-line disabled:text-mute';
function Avatar() {
  return <span className="grid size-8 shrink-0 place-items-center rounded-full bg-brand-soft text-navy" aria-hidden><Bot className="size-4" /></span>;
}
const cardCls = 'overflow-hidden rounded-2xl border border-line bg-paper';

/** 에이전트 답변 텍스트: 빈 줄은 문단, "- "로 시작하는 줄은 목록으로 보여 준다(마크다운 일부만) */
function TextBubble({ text }: { text: string }) {
  const LIST = /^\s*[-•*]\s+/;
  // 연속된 목록 줄은 하나의 목록으로, 나머지 줄은 빈 줄 기준 문단으로 묶는다
  const groups: { list: boolean; lines: string[] }[] = [];
  for (const line of text.trim().split('\n')) {
    const list = LIST.test(line);
    const last = groups.at(-1);
    if (!line.trim()) { if (last && !last.list) groups.push({ list: false, lines: [] }); continue; }
    if (last && last.list === list && (list || last.lines.length)) last.lines.push(line);
    else groups.push({ list, lines: [line] });
  }
  return (
    <div className={`${bubble} space-y-2`}>
      {groups.filter((g) => g.lines.length).map((g, i) => g.list ? (
        <ul key={i} className="space-y-1">{g.lines.map((l, k) => (
          <li key={k} className="flex gap-2"><span aria-hidden className="mt-[0.65em] size-1 shrink-0 rounded-full bg-sub" /><span className="min-w-0">{l.replace(LIST, '')}</span></li>
        ))}</ul>
      ) : <p key={i} className="whitespace-pre-line">{g.lines.join('\n')}</p>)}
    </div>
  );
}

function BlockView({ b, active, onAsk, onInput, onGo, onConfirm, onCancel, onCheckResult }: {
  b: Block; active: boolean; onAsk: (t: string, label?: string) => void; onInput: () => void; onGo: (to: string) => void; onConfirm: () => void; onCancel: () => void;
  onCheckResult: () => void;
}) {
  const { myAccounts } = useBank();
  switch (b.kind) {
    case 'spendingInsight':
    case 'forecastInsight':
    case 'subscriptionInsight':
    case 'recommendationInsight':
      return <InsightCard block={b} onGo={onGo} />;
    case 'text':
      return <TextBubble text={b.text} />;

    case 'accounts':
      return (
        <div className={cardCls}>
          {b.items.map((a) => (
            <button key={a.id} onClick={() => onGo(`/accounts/${a.id}`)} className="flex w-full items-center justify-between border-b border-line px-4 py-3 text-left last:border-0 hover:bg-surface">
              <span><span className="block text-[14px] font-semibold">{a.name}</span><span className="num block text-[12px] text-sub">{a.number}</span></span>
              <span className="num text-[16px] font-bold">{won(a.balance)}</span>
            </button>
          ))}
        </div>
      );

    case 'transactions':
      return (
        <div className={cardCls}>
          <p className="border-b border-line px-4 py-2.5 text-[13px] font-semibold text-sub">{b.title} 최근 거래</p>
          {b.items.map((t) => (
            <div key={t.id} className="flex items-center justify-between px-4 py-2.5">
              <span><span className="block text-[14px] font-medium">{t.counterparty}</span><span className="block text-[12px] text-sub">{fmtDay(t.date)}</span></span>
              <span className={cn('num text-[14px] font-semibold', t.type === 'in' && 'text-success')}>{signedWon(t.amount, t.type)}</span>
            </div>
          ))}
        </div>
      );

    case 'cardUsage':
      return (
        <div className={cardCls}>
          <div className="flex items-baseline justify-between px-4 pt-3">
            <p className="text-[14px] font-semibold">{b.month} 카드 사용</p>
            <p className="num font-display text-[20px] font-bold text-navy">{won(b.total)}</p>
          </div>
          <div className="border-b border-line px-4 py-2">
            {b.cards.map((c) => <Row key={c.id} label={`${c.name} ··${c.last4}`}><span className="num">{won(c.total)} · {c.count}건</span></Row>)}
          </div>
          {b.items.map((t) => (
            <div key={t.id} className="flex items-center justify-between px-4 py-2.5">
              <span><span className="block text-[14px] font-medium">{t.merchant}</span><span className="block text-[12px] text-sub">{fmtDay(t.date)}</span></span>
              <span className="num text-[14px] font-semibold">{won(t.amount)}</span>
            </div>
          ))}
        </div>
      );

    case 'spending': {
      const max = b.breakdown?.[0]?.total ?? 0;
      const cmp = b.compare && (b.compare.diff === 0 ? `${b.compare.label}과 같아요` : `${b.compare.label}보다 ${won(Math.abs(b.compare.diff))} ${b.compare.diff > 0 ? '더' : '덜'} 썼어요`);
      return (
        <div className={cardCls}>
          <div className="flex items-baseline justify-between px-4 pt-3">
            <p className="text-[14px] font-semibold">{b.title}</p>
            <p className="num font-display text-[20px] font-bold">{won(b.total)}</p>
          </div>
          <p className="px-4 text-[13px] text-sub">{b.count}건{cmp ? ` · ${cmp}` : ''}</p>
          {b.breakdown && (
            <ul className="space-y-2.5 px-4 pt-3">
              {b.breakdown.map((c) => (
                <li key={c.category}>
                  <div className="flex justify-between text-[13px]"><span>{c.category}</span><span className="num font-semibold">{won(c.total)}</span></div>
                  <div className="mt-1 h-1.5 rounded-full bg-surface"><div className="h-full rounded-full bg-brand" style={{ width: `${Math.max(4, (c.total / max) * 100)}%` }} /></div>
                </li>
              ))}
            </ul>
          )}
          <div className="mt-3 border-t border-line py-1">
            {b.items.map((t) => (
              <div key={t.id} className="flex items-center justify-between px-4 py-2">
                <span><span className="block text-[14px] font-medium">{t.merchant}</span><span className="block text-[12px] text-sub">{fmtDay(t.date)}</span></span>
                <span className="num text-[14px] font-semibold">{won(t.amount)}</span>
              </div>
            ))}
          </div>
        </div>
      );
    }

    case 'products':
      return (
        <div className="space-y-2">
          {b.productIds.map((id, i) => {
            const p = productById(id)!;
            return (
              <div key={id} className={cn(cardCls, 'p-4')}>
                <div className="flex items-start gap-3">
                  <span className="num w-4 shrink-0 pt-0.5 text-[15px] font-bold text-sub">{i + 1}</span>
                  <div className="min-w-0 flex-1">
                    <p className="text-[15px] font-bold">{p.name}</p>
                    <p className="text-[13px] text-sub">{p.tagline}</p>
                    <p className="num mt-1.5 text-[17px] font-bold text-brand">최고 연 {p.rate.toFixed(1)}% <span className="text-[12px] font-normal text-sub">기본 {p.baseRate.toFixed(1)}%</span></p>
                  </div>
                </div>
                <Button size="sm" variant="secondary" full className="mt-3" onClick={() => onGo(`/products/${id}`)}>상세 보기</Button>
              </div>
            );
          })}
        </div>
      );

    case 'productInfo': {
      const p = productById(b.productId)!;
      const items = b.field === 'conditions' ? [...p.target, ...p.conditions] : b.field === 'benefits' ? p.benefits : b.field === 'notices' ? p.notices : p.rateTable.map((r) => `${r.label}: ${r.rate}`);
      return (
        <div className={cn(cardCls, 'p-4')}>
          <p className="text-[15px] font-bold">{p.name}</p>
          <ul className="mt-2 space-y-1.5">
            {items.map((t) => <li key={t} className="flex gap-2 text-[14px]"><CircleCheck className="mt-0.5 size-4 shrink-0 text-brand" />{t}</li>)}
          </ul>
          <p className="mt-3 text-[12px] text-sub">예시 데이터 기준</p>
        </div>
      );
    }

    case 'choices':
      return (
        <div>
          {b.title && <p className="mb-1.5 text-[13px] font-semibold text-sub">{b.title}</p>}
          <div className="flex flex-wrap gap-2">
            {b.options.map((o) => (
              <button key={o.value ?? o.label} disabled={!active}
                onClick={() => o.value === undefined ? onInput() : onAsk(o.value, b.title ? o.label : undefined)} className={chip}>
                {o.label}
              </button>
            ))}
          </div>
        </div>
      );

    case 'agentConfirm':
      return <div className={cn(cardCls, 'border-brand/30')}>
        <p className="px-4 pt-3 text-[16px] font-semibold">요청 내용을 확인해 주세요</p>
        <div className="px-4 py-2">{Object.entries(b.display).map(([key, value]) => <Row key={key} label={key}>{typeof value === 'number' ? won(value) : value}</Row>)}</div>
        {b.status === 'pending' || b.status === 'processing'
          ? <div className="grid grid-cols-2 gap-2 px-4 pb-4"><Button variant="secondary" disabled={b.status === 'processing'} onClick={onCancel}>취소</Button><Button loading={b.status === 'processing'} onClick={onConfirm}>{b.actionType === 'AUTO_TRANSFER' ? '확인하고 등록' : '확인하고 실행'}</Button></div>
          : b.status === 'unknown'
            ? <div className="space-y-2 border-t border-line p-3 text-center">
                <p className="text-[14px] text-sub">{b.actionType === 'AUTO_TRANSFER' ? '자동이체 등록 여부를 아직 확인하지 못했어요.' : '송금 결과를 아직 확인하지 못했어요.'}</p>
                <Button size="sm" variant="secondary" onClick={onCheckResult}>{b.actionType === 'AUTO_TRANSFER' ? '등록 결과 확인' : '송금 결과 확인'}</Button>
              </div>
            : <p className="border-t border-line py-3 text-center text-[14px] text-sub">{b.status === 'done' ? '처리됨' : b.status === 'cancelled' ? '취소됨' : '실패'}</p>}
      </div>;

    case 'transferConfirm': {
      const from = myAccounts.find((a) => a.id === b.draft.fromId);
      const pending = b.status === 'pending' || b.status === 'processing';
      return (
        <div className={cn(cardCls, 'border-brand/30')}>
          <div className="px-4 pt-3 pb-1">
            <p className="text-[15px] leading-snug font-semibold">{b.draft.toName}님에게 <span className="num text-brand">{won(b.draft.amount)}</span>을 {b.draft.runAt ? '예약할까요' : '보낼까요'}?</p>
          </div>
          <div className="px-4 pb-2">
            <Row label="보내는 계좌"><span className="block">{from?.name}</span><span className="num block text-[12px] font-normal text-sub">{from?.number}</span></Row>
            <Row label="받는 분">{b.draft.toName}</Row>
            <Row label="받는 계좌"><span className="num">내금고 {b.draft.toNumber}</span></Row>
            {b.draft.runAt && <Row label="보낼 시각"><span className="num text-brand">{fmtDateTime(b.draft.runAt)}</span></Row>}
            <Row label="수수료"><span className="num">0원</span></Row>
          </div>
          {pending ? (
            <div className="grid grid-cols-2 gap-2 px-4 pb-4">
              <Button variant="secondary" onClick={onCancel} disabled={b.status === 'processing'}>취소</Button>
              <Button onClick={onConfirm} loading={b.status === 'processing'}>{b.draft.runAt ? '예약하기' : '송금하기'}</Button>
            </div>
          ) : (
            <p className={cn('border-t border-line px-4 py-3 text-center text-[14px] font-medium', b.status === 'done' ? 'text-success' : 'text-sub')}>
              {b.status === 'done' ? (b.draft.runAt ? '예약 완료' : '송금 완료') : b.status === 'failed' ? (b.draft.runAt ? '예약 실패' : '송금 실패') : '취소됨'}
            </p>
          )}
        </div>
      );
    }

    case 'scheduledList':
      return (
        <ul className={cn(cardCls, 'px-4 py-1')}>
          {b.items.map((x) => (
            <li key={x.id} className="border-b border-line/60 py-2.5 last:border-0">
              <p className="text-[15px] font-medium">{x.toName}님에게 <span className="num">{won(x.amount)}</span></p>
              <p className="num text-[13px] text-sub">{fmtDateTime(x.runAt)} · {x.fromName}</p>
            </li>
          ))}
        </ul>
      );

    case 'links':
      return (
        <div className="flex flex-wrap gap-2">
          {b.links.map((l) => (
            <button key={l.to + l.label} onClick={() => onGo(l.to)} className="inline-flex h-9 items-center gap-1 rounded-full border border-line bg-paper px-3.5 text-[13px] font-semibold text-navy hover:bg-surface">
              {l.label}<ArrowRight className="size-3.5" />
            </button>
          ))}
        </div>
      );

    case 'result':
      return (
        <div className={cn('rounded-2xl px-4 py-3', b.ok ? 'bg-success-soft' : 'bg-danger-soft')}>
          <p className={cn('flex items-center gap-1.5 text-[15px] font-bold', b.ok ? 'text-success' : 'text-danger')}>
            {b.ok ? <CircleCheck className="size-5" /> : <CircleAlert className="size-5" />}{b.title}
          </p>
          {b.lines.map((l) => <p key={l} className="num mt-1 text-[14px] text-ink">{l}</p>)}
        </div>
      );
  }
}

