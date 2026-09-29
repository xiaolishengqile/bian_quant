import { useState } from 'react';
import { KeyRound } from 'lucide-react';
import { Modal, PanelHeading } from '../components/UI';
import type { ConsoleState } from '../types';

type Environment = 'testnet' | 'live';

export default function CredentialForm({ state, authRequired, busy, save, remove }: {
  state: ConsoleState; authRequired: boolean; busy: boolean;
  save: (mode: Environment, key: string, secret: string, password: string) => Promise<boolean>;
  remove: (mode: Environment, password: string) => Promise<boolean>;
}) {
  const [mode, setMode] = useState<Environment>('testnet');
  const [key, setKey] = useState('');
  const [secret, setSecret] = useState('');
  const [password, setPassword] = useState('');
  const [removing, setRemoving] = useState(false);
  const managed = mode === 'live' ? state.connections.live_managed : state.connections.testnet_managed;
  const configured = mode === 'live' ? state.connections.live_configured : state.connections.testnet_configured;
  const locked = busy || !authRequired || state.status.state === 'running' || state.positions.length > 0;
  const clear = () => { setKey(''); setSecret(''); setPassword(''); };

  return <section className="panel settings-panel">
    <PanelHeading title="录入交易密钥" extra={<KeyRound size={17} />} />
    <form className="form-section-content" autoComplete="off" onSubmit={async event => {
      event.preventDefault();
      if (await save(mode, key, secret, password)) clear();
    }}>
      <p className="settings-description">密钥只提交给当前服务器，保存后不回显。请在币安仅开启读取和合约交易权限，不要开启提现权限，并限制服务器出口地址。</p>
      <div className="form-grid">
        <label className="field">交易环境<select value={mode} disabled={busy} onChange={event => { setMode(event.target.value as Environment); clear(); }}><option value="testnet">币安测试网</option><option value="live">币安实盘</option></select><small>{configured ? managed ? '已由网页保存，可在此更换或移除。' : '由服务器环境变量提供；网页保存后优先使用网页密钥。' : '尚未配置密钥。'}</small></label>
        <label className="field">接口标识<input type="password" value={key} autoComplete="off" disabled={locked} maxLength={512} onChange={event => setKey(event.target.value)} placeholder="粘贴币安提供的接口标识" /></label>
        <label className="field">签名密钥<input type="password" value={secret} autoComplete="new-password" disabled={locked} maxLength={512} onChange={event => setSecret(event.target.value)} placeholder="粘贴币安提供的签名密钥" /></label>
        <label className="field">再次输入工作台口令<input type="password" value={password} autoComplete="current-password" disabled={locked} onChange={event => setPassword(event.target.value)} placeholder="用于确认本次密钥操作" /></label>
      </div>
      {!authRequired && <p className="field-help">请先在服务器设置至少 12 位工作台口令并重启，才能通过网页保存密钥。</p>}
      {(state.status.state === 'running' || state.positions.length > 0) && <p className="field-help">请先停止策略并确认空仓，再修改密钥。</p>}
      <div className="reset-content"><button className="button primary" type="submit" disabled={locked || !key || !secret || !password}>保存密钥</button>{managed && <button className="button danger-outline" type="button" disabled={locked || !password} onClick={() => setRemoving(true)}>移除网页密钥</button>}</div>
      <p className="field-help">远程访问须使用加密网页连接。实盘部署开关和工作台口令仍由服务器单独管理。</p>
    </form>
    {removing && <Modal title="移除网页密钥" danger confirmLabel="确认移除" busy={busy} onClose={() => setRemoving(false)} onConfirm={async () => { if (await remove(mode, password)) { clear(); setRemoving(false); } }}><p>将移除当前环境由网页保存的交易密钥。若服务器环境变量仍有密钥，移除后会重新使用服务器密钥。</p></Modal>}
  </section>;
}
