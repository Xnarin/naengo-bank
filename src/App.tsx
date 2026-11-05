import { useEffect, useRef } from 'react';
import { Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom';
import { Toast } from './components/ui';
import { useBank } from './store';
import { Login, ResetPassword, Signup } from './pages/Auth';
import { Settings, Withdraw } from './pages/Settings';
import { Home } from './pages/Home';
import { AccountDetail } from './pages/AccountDetail';
import { AccountManage, CloseAccount } from './pages/AccountManage';
import { Transfer } from './pages/Transfer';
import { OpenAccount, ProductDetail, ProductList } from './pages/Products';
import { CardDetail, CardList, IssueCard } from './pages/Cards';
import { Assistant } from './pages/Assistant';
import { Notifications } from './pages/Notifications';
import { AutoTransfers, NewAutoTransfer } from './pages/AutoTransfers';

function RequireAuth() {
  const { user, loading, loadError, refresh, logout } = useBank();
  const loc = useLocation();
  const refreshRef = useRef(refresh); refreshRef.current = refresh;
  useEffect(() => { void refreshRef.current(true); }, [loc.key]);
  if (!user && loading) return <p role="status" className="px-5 py-20 text-center text-sub">계좌 정보를 불러오고 있어요.</p>;
  if (!user && loadError) return (
    <div className="space-y-4 px-5 py-20 text-center">
      <p role="alert" className="text-danger">{loadError}</p>
      <button onClick={() => void refresh()} className="rounded-full bg-brand px-5 py-3 font-semibold text-white">다시 시도</button>
      <button onClick={logout} className="block w-full text-sub underline">로그인 화면으로</button>
    </div>
  );
  return user ? <Outlet /> : <Navigate to="/login" replace state={{ from: loc.pathname + loc.search }} />;
}

export default function App() {
  return (
    <div className="relative mx-auto min-h-dvh w-full max-w-[430px] bg-paper shadow-[0_0_40px_rgba(14,30,74,0.08)]">
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/signup" element={<Signup />} />
        <Route path="/reset-password" element={<ResetPassword />} />
        <Route element={<RequireAuth />}>
          <Route path="/" element={<Home />} />
          <Route path="/accounts/:id" element={<AccountDetail />} />
          <Route path="/accounts/:id/manage" element={<AccountManage />} />
          <Route path="/accounts/:id/close" element={<CloseAccount />} />
          <Route path="/transfer" element={<Transfer />} />
          <Route path="/products" element={<ProductList />} />
          <Route path="/products/:id" element={<ProductDetail />} />
          <Route path="/products/:id/open" element={<OpenAccount />} />
          <Route path="/cards" element={<CardList />} />
          <Route path="/cards/new" element={<IssueCard />} />
          <Route path="/cards/:id" element={<CardDetail />} />
          <Route path="/assistant" element={<Assistant />} />
          <Route path="/notifications" element={<Notifications />} />
          <Route path="/auto-transfers" element={<AutoTransfers />} />
          <Route path="/auto-transfers/new" element={<NewAutoTransfer />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/settings/withdraw" element={<Withdraw />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      <Toast />
    </div>
  );
}
