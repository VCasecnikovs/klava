import { sparkSVG } from '@/lib/utils';

interface SparklineProps {
  series?: number[];
  color: string;
}

export function Sparkline({ series, color }: SparklineProps) {
  const svg = sparkSVG(series, color);
  if (!svg) return null;
  return <span dangerouslySetInnerHTML={{ __html: svg }} />;
}
