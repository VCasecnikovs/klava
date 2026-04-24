// Lightweight socket stub for Klava tab.
// Real-time updates come from React Query polling (3s when active).
// TODO: wire up real socket.io connection for instant event delivery.

/* eslint-disable @typescript-eslint/no-explicit-any */
const noop = (..._args: any[]) => {};
const noopSocket = {
  on: noop as (...args: any[]) => void,
  off: noop as (...args: any[]) => void,
  emit: noop as (...args: any[]) => void,
};

export function useSocket() {
  return noopSocket;
}
