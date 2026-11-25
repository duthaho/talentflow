import { createHash } from "node:crypto";
import { createClient } from "redis";

export type StoredSession = {
  subject: string;
  tenantId: string;
  email: string;
  name: string;
  accessToken: string;
  accessTokenExpiresAt: number;
  refreshToken?: string;
  idToken?: string;
};

export type PendingLogin = {
  codeVerifier: string;
  state: string;
  nonce: string;
  returnTo: string;
};

export interface KeyValueStore {
  get(key: string): Promise<string | null>;
  set(key: string, value: string, ttlSeconds: number): Promise<void>;
  delete(key: string): Promise<void>;
  take(key: string): Promise<string | null>;
}

// Redis keys hold a hash of the cookie value so a Redis dump cannot be replayed as cookies.
function keyFor(kind: "session" | "login", id: string): string {
  return `tf:web:${kind}:${createHash("sha256").update(id).digest("hex")}`;
}

export class SessionStore {
  constructor(private readonly store: KeyValueStore) {}

  async getSession(id: string): Promise<StoredSession | null> {
    const raw = await this.store.get(keyFor("session", id));
    return raw ? (JSON.parse(raw) as StoredSession) : null;
  }

  async saveSession(id: string, session: StoredSession, ttlSeconds: number): Promise<void> {
    await this.store.set(keyFor("session", id), JSON.stringify(session), ttlSeconds);
  }

  async deleteSession(id: string): Promise<void> {
    await this.store.delete(keyFor("session", id));
  }

  async savePendingLogin(id: string, login: PendingLogin, ttlSeconds: number): Promise<void> {
    await this.store.set(keyFor("login", id), JSON.stringify(login), ttlSeconds);
  }

  async takePendingLogin(id: string): Promise<PendingLogin | null> {
    const raw = await this.store.take(keyFor("login", id));
    return raw ? (JSON.parse(raw) as PendingLogin) : null;
  }
}

export class MemoryKeyValueStore implements KeyValueStore {
  private readonly entries = new Map<string, { value: string; expiresAt: number }>();

  constructor(private readonly now: () => number = Date.now) {}

  async get(key: string): Promise<string | null> {
    const entry = this.entries.get(key);
    if (!entry) return null;
    if (entry.expiresAt <= this.now()) {
      this.entries.delete(key);
      return null;
    }
    return entry.value;
  }

  async set(key: string, value: string, ttlSeconds: number): Promise<void> {
    this.entries.set(key, { value, expiresAt: this.now() + ttlSeconds * 1000 });
  }

  async delete(key: string): Promise<void> {
    this.entries.delete(key);
  }

  async take(key: string): Promise<string | null> {
    const value = await this.get(key);
    this.entries.delete(key);
    return value;
  }

  size(): number {
    return this.entries.size;
  }
}

export class RedisKeyValueStore implements KeyValueStore {
  private client: ReturnType<typeof createClient> | undefined;
  private connecting: Promise<unknown> | undefined;

  constructor(private readonly url: string) {}

  private async connected() {
    if (!this.client) {
      this.client = createClient({ url: this.url });
      this.client.on("error", (error: unknown) => console.error("redis session store error", error));
      this.connecting = this.client.connect();
    }
    await this.connecting;
    return this.client;
  }

  async get(key: string): Promise<string | null> {
    return (await this.connected()).get(key);
  }

  async set(key: string, value: string, ttlSeconds: number): Promise<void> {
    await (await this.connected()).set(key, value, { expiration: { type: "EX", value: ttlSeconds } });
  }

  async delete(key: string): Promise<void> {
    await (await this.connected()).del(key);
  }

  async take(key: string): Promise<string | null> {
    return (await this.connected()).getDel(key);
  }
}
