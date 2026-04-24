import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';

const DEFAULT_VADIMGEST_URL = 'http://localhost:8484';

function readNestedString(obj: unknown, dottedKey: string): string | undefined {
  const parts = dottedKey.split('.');
  let cur: unknown = obj;
  for (const p of parts) {
    if (cur && typeof cur === 'object' && p in (cur as Record<string, unknown>)) {
      cur = (cur as Record<string, unknown>)[p];
    } else {
      return undefined;
    }
  }
  return typeof cur === 'string' && cur ? cur : undefined;
}

/**
 * Returns the user-configured Vadimgest dashboard URL
 * (paths.vadimgest_url in config.yaml), falling back to
 * http://localhost:8484 when the settings endpoint hasn't loaded
 * yet or the value is unset. Cached via react-query so the
 * three consumers (Pulse, Health, Sources) share one fetch.
 */
export function useVadimgestUrl(): string {
  const { data } = useQuery({
    queryKey: ['settings', 'paths.vadimgest_url'],
    queryFn: api.settings,
    staleTime: 5 * 60 * 1000,
  });
  return readNestedString(data?.config, 'paths.vadimgest_url') ?? DEFAULT_VADIMGEST_URL;
}
