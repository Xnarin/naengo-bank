import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { BellOff } from 'lucide-react';
import { shortName } from '../components/bank';
import { EmptyState, Page } from '../components/ui';
import { cn, fmtDateTime, fmtDay, fmtTime, groupByDay, won } from '../lib/format';
import { useBank } from '../store';

const KIND = { in: { label: '입금', cls: 'text-success' }, scheduled: { label: '예약 송금', cls: 'text-brand' }, failed: { label: '이체 실패', cls: 'text-danger' }, card: { label: '카드 결제', cls: 'text-navy' }, auto: { label: '자동이체', cls: 'text-brand' } };

export function Notifications() {
  const { db, user, myAccounts, notices, markNoticesRead, cancelScheduled, toast } = useBank();
  const navigate = useNavigate();
  // 들어올 때의 확인 시각을 붙잡아 두고 바로 읽음 처리 → 이번 방문 동안은 새 알림 표시가 남는다
  const [seenAt] = useState(() => (user && db.readAt[user.email]) || '');
  useEffect(() => { markNoticesRead(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const waiting = db.scheduled.filter((x) => x.owner === user?.email && x.status === 'waiting').sort((a, b) => a.runAt.localeCompare(b.runAt));
  const accName = (id: string) => shortName(myAccounts.find((a) => a.id === id)?.name ?? '');

  return (
    <Page back title="알림" nav>
      {waiting.length > 0 && (
        <section className="pt-2 pb-4">
          <h2 className="text-[13px] font-medium text-sub">보낼 예정 {waiting.length}건</h2>
          <ul>
            {waiting.map((x) => (
              <li key={x.id} className="flex items-center gap-3 border-b border-line/60 py-3 last:border-0">
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[15px] font-medium">{x.toName}님에게 <span className="num">{won(x.amount)}</span></span>
                  <span className="num block text-[13px] text-sub">{fmtDateTime(x.runAt)} · {accName(x.fromId)}에서</span>
                </span>
                <button onClick={() => { cancelScheduled(x.id); toast('예약을 취소했어요'); }}
                  className="h-8 shrink-0 rounded-full border border-line px-3 text-[13px] font-medium text-sub hover:bg-surface">취소</button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {notices.length ? (
        groupByDay(notices).map((g) => (
          <section key={g[0].date} className="border-t border-line py-2">
            <h3 className="pt-2 text-[13px] font-medium text-sub">{fmtDay(g[0].date)}</h3>
            {g.map((n) => {
              const fresh = n.date > seenAt;
              return (
                <button key={n.id} onClick={() => navigate(n.to)} className="flex w-full items-start gap-3 py-3 text-left">
                  <span aria-hidden className={cn('mt-2 size-1.5 shrink-0 rounded-full', fresh ? 'bg-brand' : 'bg-transparent')} />
                  <span className="min-w-0 flex-1">
                    <span className={cn('block text-[12px] font-semibold', KIND[n.kind].cls)}>{KIND[n.kind].label}{fresh && <span className="sr-only"> (새 알림)</span>}</span>
                    <span className={cn('block text-[15px] leading-snug', fresh ? 'font-semibold' : 'font-medium')}>{n.title}</span>
                    <span className="block text-[13px] text-sub">{fmtTime(n.date)}{n.sub && ` · ${n.sub}`}</span>
                  </span>
                </button>
              );
            })}
          </section>
        ))
      ) : (
        <EmptyState icon={BellOff} title="아직 알림이 없어요" desc="입금이나 예약 송금 결과가 생기면 여기에 모여요." />
      )}
    </Page>
  );
}
