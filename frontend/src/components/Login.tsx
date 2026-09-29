import { useState } from 'react';
import { ArrowRight, LockKeyhole, ShieldCheck } from 'lucide-react';
import { Logo } from './UI';

export default function Login({ login, busy, error }: { login: (password: string) => Promise<void>; busy: boolean; error: string }) {
  const [password, setPassword] = useState('');
  return <main className="auth-screen"><div className="auth-grain" /><section className="login-panel">
    <div className="login-brand"><Logo /><span>衡量<span className="brand-subtitle">个人量化工作台</span></span></div>
    <div className="login-symbol"><LockKeyhole size={26} strokeWidth={1.5} /></div>
    <h1>回到你的交易工作台</h1><p>输入服务器访问口令，安全连接你的策略。</p>
    <form onSubmit={event => { event.preventDefault(); void login(password); }}>
      <label className="field">访问口令<input type="password" autoComplete="current-password" required autoFocus value={password} onChange={event => setPassword(event.target.value)} placeholder="请输入控制台访问口令" /></label>
      {error && <div className="inline-error" role="alert">{error}</div>}
      <button className="button primary" type="submit" disabled={busy || !password}>{busy ? '正在验证' : '进入工作台'}<ArrowRight size={16} /></button>
    </form>
    <div className="login-note"><ShieldCheck size={15} /><span>交易密钥提交后仅由服务器保管，页面不会回显。</span></div>
  </section><div className="login-footer">保持理性 · 尊重风险 · 让策略有迹可循</div></main>;
}
