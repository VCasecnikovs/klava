// Mock socket that captures event handlers and lets tests emit events
type Handler = (...args: unknown[]) => void;

class MockSocket {
  private handlers: Map<string, Set<Handler>> = new Map();
  connected = false;
  id = 'mock-socket-id';
  // Mimic socket.io.engine.transport.name accessed in ChatContext connect handler
  io = { engine: { transport: { name: 'websocket' } } };

  on(event: string, handler: Handler) {
    if (!this.handlers.has(event)) this.handlers.set(event, new Set());
    this.handlers.get(event)!.add(handler);
    return this;
  }

  off(event: string, handler?: Handler) {
    if (handler) {
      this.handlers.get(event)?.delete(handler);
    } else {
      this.handlers.delete(event);
    }
    return this;
  }

  emit(event: string, ...args: unknown[]) {
    // Track emitted events for assertions
    MockSocket.emitted.push({ event, args });
    return this;
  }

  // Test helpers
  simulateEvent(event: string, ...args: unknown[]) {
    const handlers = this.handlers.get(event);
    if (handlers) {
      handlers.forEach(h => h(...args));
    }
  }

  simulateConnect() {
    this.connected = true;
    this.simulateEvent('connect');
  }

  simulateDisconnect() {
    this.connected = false;
    this.simulateEvent('disconnect');
  }

  disconnect() {
    this.connected = false;
  }

  static emitted: Array<{ event: string; args: unknown[] }> = [];
  static resetEmitted() { MockSocket.emitted = []; }
  static instance: MockSocket | null = null;
}

function io(_url: string, _opts?: unknown): MockSocket {
  const socket = new MockSocket();
  MockSocket.instance = socket;
  // Auto-connect after a tick (simulates async connection)
  setTimeout(() => socket.simulateConnect(), 0);
  return socket;
}

export { io, MockSocket };
export type { Socket } from 'socket.io-client';
