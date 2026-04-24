import { cn } from '@/lib/utils';

interface BadgeProps {
  count: number;
  style?: 'subtle' | 'danger' | '';
}

export function Badge({ count, style = '' }: BadgeProps) {
  if (count <= 0) return null;
  return (
    <span className={cn('tab-badge', style || undefined)}>
      {count}
    </span>
  );
}
