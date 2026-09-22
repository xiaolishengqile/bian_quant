"""按交易模式和行情来源隔离账户，成交与状态原子保存。"""
import json
import sqlite3
from pathlib import Path


def account_key(config: dict) -> str:
    return f"{config['mode']}:{config['market_source']}"


class Storage:
    def __init__(self, path: str):
        if path != ':memory:':
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # 宿主在启动线程构造、事件循环线程使用；引擎的异步锁负责串行访问。
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.execute('PRAGMA journal_mode=WAL')
        self.connection.execute('PRAGMA synchronous=FULL')
        self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS accounts (namespace TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS intents (id TEXT PRIMARY KEY, status TEXT NOT NULL, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS orders (seq INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp INTEGER NOT NULL,
                level TEXT NOT NULL, message TEXT NOT NULL);
        ''')
        active = self.load()
        self.namespace = account_key(active['config']) if active else 'paper:demo'
        with self.connection:
            for table in ('intents', 'orders', 'logs'):
                columns = [row[1] for row in self.connection.execute(f'PRAGMA table_info({table})')]
                if 'namespace' not in columns:
                    self.connection.execute(f"ALTER TABLE {table} ADD COLUMN namespace TEXT NOT NULL DEFAULT ''")
                self.connection.execute(f"UPDATE {table} SET namespace=? WHERE namespace=''", (self.namespace,))
            if active:
                self._save(active)

    def load(self) -> dict | None:
        row = self.connection.execute('SELECT data FROM state WHERE id=1').fetchone()
        return json.loads(row[0]) if row else None

    def load_account(self, config: dict) -> dict | None:
        row = self.connection.execute('SELECT data FROM accounts WHERE namespace=?', (account_key(config),)).fetchone()
        return json.loads(row[0]) if row else None

    def _save(self, state: dict):
        self.namespace = account_key(state['config'])
        serialized = json.dumps(state, allow_nan=False)
        self.connection.execute('INSERT INTO state VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET data=excluded.data', (serialized,))
        self.connection.execute('INSERT INTO accounts VALUES (?, ?) ON CONFLICT(namespace) DO UPDATE SET data=excluded.data',
                                (self.namespace, serialized))

    def save(self, state: dict):
        with self.connection:
            self._save(state)

    def intent(self, order: dict):
        with self.connection:
            self.connection.execute('INSERT INTO intents(id, status, data, namespace) VALUES (?, ?, ?, ?)',
                                    (order['id'], 'pending', json.dumps(order, allow_nan=False), self.namespace))

    def complete(self, order: dict, state: dict):
        with self.connection:
            self.connection.execute('UPDATE intents SET status=? WHERE id=?', (order['status'], order['id']))
            self.connection.execute('INSERT INTO orders(data, namespace) VALUES (?, ?)',
                                    (json.dumps(order, allow_nan=False), self.namespace))
            self._save(state)

    def mark_unknown(self, order_id: str, state: dict):
        with self.connection:
            self.connection.execute('UPDATE intents SET status=? WHERE id=?', ('unknown', order_id))
            self._save(state)

    def unresolved(self) -> list[dict]:
        return [dict(json.loads(row[0]), status=row[1]) for row in self.connection.execute(
            "SELECT data, status FROM intents WHERE status IN ('pending', 'unknown') AND namespace=?", (self.namespace,))]

    def orders(self) -> list[dict]:
        filled = [json.loads(row[0]) for row in self.connection.execute(
            'SELECT data FROM orders WHERE namespace=? ORDER BY seq DESC LIMIT 200', (self.namespace,))]
        pending = [dict(quantity=0, price=0, fee=0, realized_pnl=0, **order) for order in self.unresolved()]
        return sorted(pending+filled, key=lambda order: order['timestamp'], reverse=True)[:200]

    def log(self, timestamp: int, level: str, message: str):
        with self.connection:
            self.connection.execute('INSERT INTO logs(timestamp, level, message, namespace) VALUES (?, ?, ?, ?)',
                                    (timestamp, level, message, self.namespace))

    def logs(self) -> list[dict]:
        return [dict(zip(('id', 'timestamp', 'level', 'message'), row)) for row in self.connection.execute(
            'SELECT id, timestamp, level, message FROM logs WHERE namespace=? ORDER BY id DESC LIMIT 200', (self.namespace,))]

    def reset(self, state: dict):
        with self.connection:
            self.connection.execute('DELETE FROM orders WHERE namespace=?', (self.namespace,))
            self.connection.execute('DELETE FROM intents WHERE namespace=?', (self.namespace,))
            self._save(state)

    def close(self):
        self.connection.close()
