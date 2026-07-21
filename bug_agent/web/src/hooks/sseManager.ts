import { getApiUrl } from '../api/request';

type EventHandler = (data: any) => void;

interface ConnectionListener {
  (connected: boolean): void;
}

class SSEManager {
  private es: EventSource | null = null;
  private handlers = new Map<string, Set<EventHandler>>();
  private connectionListeners = new Set<ConnectionListener>();
  private connected = false;
  private token: string = '';
  private rooms: string[] = [];
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectCount = 0;
  private stopped = false;
  private static readonly RECONNECT_INTERVAL = 3000;
  private static readonly MAX_RECONNECT_ATTEMPTS = 10;
  private static readonly MAX_DELAY = 30000;

  connect(token: string, rooms: string[]): void {
    this.token = token;
    this.rooms = rooms;
    this.stopped = false;
    this.reconnectCount = 0;

    if (this.es) {
      this.es.close();
    }

    // SSE 与普通 API 复用同一基础地址，保证开发代理和生产网关配置一致。
    const url = `${getApiUrl('/sse')}?token=${encodeURIComponent(token)}&rooms=${encodeURIComponent(rooms.join(','))}`;

    this.es = new EventSource(url);

    this.es.onopen = () => {
      this.connected = true;
      this.reconnectCount = 0;
      this.connectionListeners.forEach((l) => l(true));
    };

    this.es.onerror = () => {
      this.connected = false;
      this.connectionListeners.forEach((l) => l(false));
      this.tryReconnect();
    };

    this.es.onmessage = () => {
      // SSE comments (keepalive) start with ':', EventSource ignores them
    };

    const eventTypes = [
      'defect:status_changed',
      'defect:created',
      'defect:updated',
      'analysis:started',
      'analysis:progress',
      'analysis:completed',
      'analysis:failed',
      'fix_task:created',
      'fix_task:progress',
      'fix_task:completed',
      'fix_task:failed',
      'comment:added',
      'collaboration:started',
      'collaboration:progress',
      'collaboration:completed',
      'notification',
    ];

    eventTypes.forEach((eventType) => {
      this.es!.addEventListener(eventType, (event: MessageEvent) => {
        try {
          const data = JSON.parse(event.data);
          const handlers = this.handlers.get(eventType);
          if (handlers) {
            handlers.forEach((handler) => handler(data));
          }
        } catch {
          // ignore parse errors
        }
      });
    });
  }

  private tryReconnect(): void {
    if (this.stopped) return;
    if (this.reconnectCount >= SSEManager.MAX_RECONNECT_ATTEMPTS) return;
    if (this.reconnectTimer) return;

    const delay = Math.min(
      SSEManager.RECONNECT_INTERVAL * Math.pow(1.5, this.reconnectCount),
      SSEManager.MAX_DELAY
    );
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.reconnectCount++;
      if (this.token && this.rooms.length > 0) {
        this.connect(this.token, this.rooms);
      }
    }, delay);
  }

  disconnect(): void {
    this.stopped = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.es) {
      this.es.close();
      this.es = null;
    }
    this.connected = false;
    this.handlers.clear();
    this.connectionListeners.forEach((l) => l(false));
  }

  on(event: string, handler: EventHandler): void {
    if (!this.handlers.has(event)) {
      this.handlers.set(event, new Set());
    }
    this.handlers.get(event)!.add(handler);
  }

  off(event: string, handler: EventHandler): void {
    const handlers = this.handlers.get(event);
    if (handlers) {
      handlers.delete(handler);
      if (handlers.size === 0) {
        this.handlers.delete(event);
      }
    }
  }

  onConnectionChange(listener: ConnectionListener): () => void {
    this.connectionListeners.add(listener);
    return () => {
      this.connectionListeners.delete(listener);
    };
  }

  isConnected(): boolean {
    return this.connected;
  }
}

export const sseManager = new SSEManager();
export default sseManager;
