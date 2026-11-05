import { useEffect, useRef, useState, type FormEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowRight, Bot, CircleAlert, CircleCheck, RotateCcw, SendHorizontal } from 'lucide-react';
import { Button, Page, Row } from '../components/ui';
import { PinSheet } from '../components/bank';
import { chatClient, isMockChat, type Block, type ChatMessage } from '../api/chat';
import { SUGGESTIONS } from '../api/mockChat';
import { productById } from '../data/mock';
import { cn, fmtDateTime, fmtDay, signedWon, won } from '../lib/format';
import { useBank } from '../store';

const uid = () => Math.random().toString(36).slice(2);

export function Assistant() {
  const bank = useBank();
  const { chat, setChat, user, db, myAccounts, myCards } = bank;
  const navigate = useNavigate();
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }); }, [chat.messages.length, busy]);

  const snapshot = () => {
    const ids = myAccounts.map((a) => a.id);
    const myTxs = db.txs.filter((t) => ids.includes(t.accountId));
    const seen = new Map<string, string>();
    for (const t of [...myTxs].sort((a, b) => b.date.localeCompare(a.date))) {
      if (t.type === 'out' && t.counterpartyAccount && !myAccounts.some((a) => a.number === t.counterpartyAccount) && !seen.has(t.counterparty)) seen.set(t.counterparty, t.counterpartyAccount);
    }
    return {
      userName: user?.name ?? '',
      accounts: myAccounts,
      txs: myTxs,
      cards: myCards,
      cardTxs: db.cardTxs,
      recipients: [...seen].map(([name, number]) => ({ name, number })),
      lookup: (no: string) => {
        const a = db.accounts.find((x) => x.number.replace(/\D/g, '') === no.replace(/\D/g, ''));
        return a ? { name: db.users.find((u) => u.email === a.owner)?.name ?? '', number: a.number } : null;
      },
      simulateError: bank.simulateError,
      scheduled: db.scheduled.filter((x) => x.owner === user?.email && x.status === 'waiting'),
    };
  };

  const push = (m: ChatMessage) => setChat((c) => ({ ...c, messages: [...c.messages, m] }));

  async function ask(text: string, addUser = true) {
    const msg = text.trim();
    if (!msg || busy) return;
    if (addUser) push({ id: uid(), role: 'user', text: msg });
    setInput('');
    setBusy(true);
    try {
      const res = await chatClient.send({ message: msg, context: chat.context, snapshot: snapshot() });
      setChat((c) => ({ messages: [...c.messages, { id: uid(), role: 'assistant', blocks: res.blocks }], context: res.context }));
    } catch {
      push({ id: uid(), role: 'assistant', retryText: msg, blocks: [{ kind: 'text', text: '응답을 불러오지 못했어요. 잠시 후 다시 시도해 주세요.' }] });
    } finally {
      setBusy(false);
    }
  }

  function retry(m: ChatMessage) {
    setChat((c) => ({ ...c, messages: c.messages.filter((x) => x.id !== m.id) }));
    ask(m.retryText!, false);
  }

  const setStatus = (msgId: string, idx: number, status: Extract<Block, { kind: 'transferConfirm' }>['status']) =>
    setChat((c) => ({
      ...c,
      messages: c.messages.map((m) => (m.id !== msgId ? m : { ...m, blocks: m.blocks!.map((b, i) => (i === idx && b.kind === 'transferConfirm' ? { ...b, status } : b)) })),
    }));

  const [pinFor, setPinFor] = useState<{ msgId: string; idx: number; b: Extract<Block, { kind: 'transferConfirm' }> } | null>(null);

  async function confirmTransfer(msgId: string, idx: number, b: Extract<Block, { kind: 'transferConfirm' }>) {
    setStatus(msgId, idx, 'processing');
    try {
      const input = { fromId: b.draft.fromId, toNumber: b.draft.toNumber, amount: b.draft.amount };
      if (b.draft.runAt) {
        await bank.scheduleTransfer({ ...input, runAt: b.draft.runAt });
        setStatus(msgId, idx, 'done');
        push({
          id: uid(), role: 'assistant', blocks: [
            { kind: 'result', ok: true, title: '송금을 예약했어요', lines: [`${fmtDateTime(b.draft.runAt)}에 ${b.draft.toName}님에게 ${won(b.draft.amount)}을 보낼게요.`, '그때 잔액이 부족하면 보내지 않고 알림으로 알려 드려요.'] },
            { kind: 'links', links: [{ label: '예약 목록 보기', to: '/notifications' }, { label: '홈으로', to: '/' }] },
          ],
        });
        return;
      }
      const r = await bank.transfer(input);
      setStatus(msgId, idx, 'done');
      push({
        id: uid(), role: 'assistant', blocks: [
          { kind: 'result', ok: true, title: '송금이 완료됐어요', lines: [`${r.toName}님에게 ${won(b.draft.amount)}을 보냈어요.`, `출금 후 잔액 ${won(r.balanceAfter)}`] },
          { kind: 'links', links: [{ label: '거래내역 보기', to: `/accounts/${b.draft.fromId}` }, { label: '홈으로', to: '/' }] },
        ],
      });
    } catch (e) {
      setStatus(msgId, idx, 'failed');
      push({
        id: uid(), role: 'assistant', blocks: [
          { kind: 'result', ok: false, title: b.draft.runAt ? '예약하지 못했어요' : '송금하지 못했어요', lines: [(e as Error).message, b.draft.runAt ? '예약은 만들어지지 않았어요.' : '송금은 실행되지 않았고 잔액은 그대로예요.'] },
          { kind: 'choices', options: [{ label: '다시 송금하기', value: '송금하고 싶어' }] },
        ],
      });
    }
  }

  function cancelTransfer(msgId: string, idx: number) {
    setStatus(msgId, idx, 'cancelled');
    push({ id: uid(), role: 'assistant', blocks: [{ kind: 'text', text: '송금을 취소했어요. 송금은 실행되지 않았어요.' }] });
  }

  const submit = (e: FormEvent) => { e.preventDefault(); ask(input); };
  const lastId = chat.messages.at(-1)?.id;

  return (
    <Page
      title="AI 은행 어시스턴트"
      nav
      right={chat.messages.length > 0 && (
        <button onClick={() => setChat({ messages: [], context: {} })} aria-label="새 대화" className="mr-1 grid size-10 place-items-center rounded-full text-sub hover:bg-surface"><RotateCcw className="size-5" /></button>
      )}
    >
      {isMockChat && <p className="-mx-5 bg-surface px-5 py-2 text-[12px] text-sub">시나리오 기반 데모 응답이에요. 금리·상품 정보는 예시 데이터예요.</p>}

        <div className="flex gap-2 pt-4">
          <Avatar />
          <div className="min-w-0 flex-1 space-y-2">
            <p className={bubble}>{user?.name}님, 안녕하세요. 잔액 조회, 거래내역, 카드 사용내역, 통장 추천, 송금을 도와드릴 수 있어요. 송금은 확인 버튼을 누르기 전까지 실행되지 않아요.</p>
            <div className="flex flex-wrap gap-2">
              {SUGGESTIONS.map((s) => (
                <button key={s} onClick={() => ask(s)} disabled={chat.messages.length > 0 || busy} className={chip}>{s}</button>
              ))}
            </div>
          </div>
        </div>

      <div className="space-y-4 pt-4" aria-live="polite">
        {chat.messages.map((m) =>
          m.role === 'user' ? (
            <div key={m.id} className="rise flex justify-end">
              <p className="max-w-[80%] rounded-2xl rounded-br-md bg-brand px-4 py-2.5 text-[15px] text-white">{m.text}</p>
            </div>
          ) : (
            <div key={m.id} className="rise flex gap-2">
              <Avatar />
              <div className="min-w-0 flex-1 space-y-2">
                {m.blocks?.map((b, i) => (
                  <BlockView key={i} b={b} active={m.id === lastId && !busy} onAsk={ask} onGo={(to) => navigate(to)}
                    onConfirm={() => b.kind === 'transferConfirm' && setPinFor({ msgId: m.id, idx: i, b })} onCancel={() => cancelTransfer(m.id, i)} />
                ))}
                {m.retryText && (
                  <Button size="sm" variant="secondary" onClick={() => retry(m)} disabled={busy}><RotateCcw className="size-3.5" />다시 시도</Button>
                )}
              </div>
            </div>
          ),
        )}
        {busy && (
          <div className="flex gap-2" aria-label="응답 작성 중">
            <Avatar />
            <span className="flex items-center gap-1 rounded-2xl rounded-tl-md bg-surface px-4 py-3">
              <span className="dot size-1.5 rounded-full bg-sub" /><span className="dot size-1.5 rounded-full bg-sub" /><span className="dot size-1.5 rounded-full bg-sub" />
            </span>
          </div>
        )}
        <div ref={endRef} className="h-28" />
      </div>

      <div className="fixed bottom-16 left-1/2 z-30 w-full max-w-[430px] -translate-x-1/2 border-t border-line bg-paper pb-[env(safe-area-inset-bottom)]">
        {chat.messages.length > 0 && (
          <div className="no-scrollbar flex gap-2 overflow-x-auto px-4 pt-2.5">
            {SUGGESTIONS.map((s) => (
              <button key={s} onClick={() => ask(s)} disabled={busy} className="h-8 shrink-0 rounded-full border border-line px-3 text-[13px] text-sub hover:bg-surface disabled:opacity-50">{s}</button>
            ))}
          </div>
        )}
        <form onSubmit={submit} className="flex items-center gap-2 px-4 py-2.5">
          <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="메시지를 입력하세요" aria-label="메시지 입력"
            className="h-11 min-w-0 flex-1 rounded-full bg-surface px-4 text-[15px] outline-none focus:ring-2 focus:ring-brand/30" />
          <button type="submit" disabled={!input.trim() || busy} aria-label="전송" className="grid size-11 shrink-0 place-items-center rounded-full bg-brand text-white disabled:bg-line">
            <SendHorizontal className="size-5" />
          </button>
        </form>
      </div>
      <PinSheet accountId={pinFor?.b.draft.fromId} open={!!pinFor} onClose={() => setPinFor(null)} onPass={() => { if (pinFor) confirmTransfer(pinFor.msgId, pinFor.idx, pinFor.b); setPinFor(null); }} />
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

function BlockView({ b, active, onAsk, onGo, onConfirm, onCancel }: {
  b: Block; active: boolean; onAsk: (t: string) => void; onGo: (to: string) => void; onConfirm: () => void; onCancel: () => void;
}) {
  const { myAccounts } = useBank();
  switch (b.kind) {
    case 'text':
      return <p className={`${bubble} whitespace-pre-line`}>{b.text}</p>;

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
        <div className="flex flex-wrap gap-2">
          {b.options.map((o) => (
            <button key={o.label} disabled={!active} onClick={() => onAsk(o.value)}
              className={chip}>
              {o.label}
            </button>
          ))}
        </div>
      );

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

