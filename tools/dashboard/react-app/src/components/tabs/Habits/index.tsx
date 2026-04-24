import { useState, useCallback } from 'react';
import { useHabits } from '@/api/queries';
import { api } from '@/api/client';

interface Habit {
  id: string;
  title: string;
  subtitle: string;
  category: string;
  frequency: string;
  icon: string;
  streak: number;
  done_today: boolean;
  video?: string;
  guide?: string;
}

interface HabitsData {
  habits: Habit[];
  today: string;
  today_done: string[];
  heatmap: Record<string, string[]>;
  total_habits: number;
  done_count: number;
}

const ICONS: Record<string, string> = {
  wind: String.fromCodePoint(0x1F32C) + '\uFE0F',
  spine: String.fromCodePoint(0x1F9B4),
  sparkles: '\u2728',
  dumbbell: String.fromCodePoint(0x1F4AA),
  mic: String.fromCodePoint(0x1F3A4),
  users: String.fromCodePoint(0x1F91D),
  phone: String.fromCodePoint(0x1F4DE),
  scale: '\u2696\uFE0F',
  hospital: String.fromCodePoint(0x1F3E5),
  video: String.fromCodePoint(0x1F3AC),
  book: String.fromCodePoint(0x1F4D6),
  beef: String.fromCodePoint(0x1F969),
  zap: '\u26A1',
  pill: String.fromCodePoint(0x1F48A),
  moon: String.fromCodePoint(0x1F319),
  snowflake: '\u2744\uFE0F',
};

const FIRE = String.fromCodePoint(0x1F525);
const STAR = '\u2B50';
const CHECK = '\u2705';
const PARTY = String.fromCodePoint(0x1F389);
const DICE = String.fromCodePoint(0x1F3B2);

const CATEGORY_COLORS: Record<string, string> = {
  health: '#4ade80',
  fitness: '#f97316',
  growth: '#a78bfa',
};

const PLAY = String.fromCodePoint(0x25B6) + '\uFE0F';

function HabitCard({ habit, onToggle, toggling }: { habit: Habit; onToggle: () => void; toggling: boolean }) {
  const [showVideo, setShowVideo] = useState(false);
  const icon = ICONS[habit.icon] || STAR;
  const catColor = CATEGORY_COLORS[habit.category] || '#888';
  const hasMedia = !!(habit.video || habit.guide);

  return (
    <div>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 14,
          width: '100%',
          padding: '14px 18px',
          border: '1px solid',
          borderColor: habit.done_today ? 'var(--border-success, #2d6a3f)' : 'var(--border, #333)',
          borderRadius: showVideo ? '12px 12px 0 0' : 12,
          background: habit.done_today
            ? 'linear-gradient(135deg, rgba(74,222,128,0.08), rgba(74,222,128,0.02))'
            : 'var(--surface, #1a1a1a)',
          textAlign: 'left' as const,
          color: 'inherit',
          transition: 'all 0.2s ease',
          opacity: toggling ? 0.6 : 1,
          position: 'relative' as const,
          overflow: 'hidden',
        }}
      >
        <button
          onClick={onToggle}
          disabled={toggling}
          style={{
            width: 42, height: 42,
            borderRadius: 10,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 22,
            background: habit.done_today ? 'rgba(74,222,128,0.15)' : 'rgba(255,255,255,0.05)',
            transition: 'all 0.2s',
            flexShrink: 0,
            border: 'none',
            cursor: toggling ? 'wait' : 'pointer',
            color: 'inherit',
            padding: 0,
          }}
        >
          {habit.done_today ? CHECK : icon}
        </button>

        <button
          onClick={onToggle}
          disabled={toggling}
          style={{
            flex: 1, minWidth: 0,
            background: 'none', border: 'none', padding: 0,
            textAlign: 'left' as const, color: 'inherit',
            cursor: toggling ? 'wait' : 'pointer',
          }}
        >
          <div style={{
            fontSize: 14, fontWeight: 600,
            textDecoration: habit.done_today ? 'line-through' : 'none',
            opacity: habit.done_today ? 0.6 : 1,
          }}>
            {habit.title}
          </div>
          <div style={{ fontSize: 12, opacity: 0.5, marginTop: 2 }}>
            {habit.subtitle}
          </div>
        </button>

        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
          {hasMedia && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                if (habit.guide && !habit.video) {
                  window.open(habit.guide, '_blank');
                } else {
                  setShowVideo(!showVideo);
                }
              }}
              style={{
                width: 32, height: 32, borderRadius: 8,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 14,
                background: showVideo ? 'rgba(167,139,250,0.2)' : 'rgba(255,255,255,0.05)',
                border: showVideo ? '1px solid rgba(167,139,250,0.4)' : '1px solid transparent',
                cursor: 'pointer', color: 'inherit', padding: 0,
                transition: 'all 0.2s',
              }}
              title={habit.video ? 'Watch video' : 'View guide'}
            >
              {habit.video ? PLAY : ICONS.book}
            </button>
          )}
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4 }}>
            {habit.streak > 0 && (
              <div style={{
                fontSize: 13, fontWeight: 700, fontVariantNumeric: 'tabular-nums',
                color: habit.streak >= 7 ? '#f59e0b' : habit.streak >= 3 ? '#4ade80' : 'var(--text-muted)',
              }}>
                {habit.streak}d {FIRE}
              </div>
            )}
            <div style={{
              fontSize: 10, fontWeight: 500,
              padding: '1px 6px', borderRadius: 4,
              background: `${catColor}22`, color: catColor,
              textTransform: 'uppercase', letterSpacing: 0.5,
            }}>
              {habit.category}
            </div>
          </div>
        </div>
      </div>

      {showVideo && habit.video && (
        <div style={{
          border: '1px solid var(--border, #333)',
          borderTop: 'none',
          borderRadius: '0 0 12px 12px',
          background: '#000',
          overflow: 'hidden',
        }}>
          <video
            controls
            autoPlay
            style={{ width: '100%', maxHeight: 400, display: 'block' }}
            src={habit.video}
          />
        </div>
      )}

      {showVideo && habit.guide && !habit.video && (
        <div style={{
          border: '1px solid var(--border, #333)',
          borderTop: 'none',
          borderRadius: '0 0 12px 12px',
          padding: '12px 18px',
          background: 'var(--surface, #1a1a1a)',
        }}>
          <a
            href={habit.guide}
            target="_blank"
            rel="noopener noreferrer"
            style={{ color: '#a78bfa', fontSize: 13, textDecoration: 'none' }}
          >
            {ICONS.book} Open exercise guide
          </a>
        </div>
      )}
    </div>
  );
}

function PickForMe({ habits, onPick }: { habits: Habit[]; onPick: (h: Habit) => void }) {
  const undone = habits.filter(h => !h.done_today);
  const [picked, setPicked] = useState<Habit | null>(null);
  const [animating, setAnimating] = useState(false);

  const doPick = useCallback(() => {
    if (undone.length === 0) return;
    setAnimating(true);
    let count = 0;
    const interval = setInterval(() => {
      const rand = undone[Math.floor(Math.random() * undone.length)];
      setPicked(rand);
      count++;
      if (count >= 8) {
        clearInterval(interval);
        setAnimating(false);
        const final = undone[Math.floor(Math.random() * undone.length)];
        setPicked(final);
      }
    }, 80);
  }, [undone]);

  if (undone.length === 0) {
    return (
      <div style={{
        textAlign: 'center', padding: '32px 20px',
        background: 'linear-gradient(135deg, rgba(74,222,128,0.1), rgba(168,85,247,0.1))',
        borderRadius: 16, margin: '0 0 20px',
      }}>
        <div style={{ fontSize: 32, marginBottom: 8 }}>{PARTY}</div>
        <div style={{ fontSize: 16, fontWeight: 700 }}>All done for today!</div>
        <div style={{ fontSize: 13, opacity: 0.6, marginTop: 4 }}>You crushed it.</div>
      </div>
    );
  }

  return (
    <div style={{
      textAlign: 'center', padding: '20px',
      background: 'var(--surface, #1a1a1a)',
      borderRadius: 16, margin: '0 0 20px',
      border: '1px solid var(--border, #333)',
    }}>
      {picked && !animating ? (
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 28, marginBottom: 4 }}>{ICONS[picked.icon] || STAR}</div>
          <div style={{ fontSize: 16, fontWeight: 700 }}>{picked.title}</div>
          <div style={{ fontSize: 12, opacity: 0.5 }}>{picked.subtitle}</div>
        </div>
      ) : picked && animating ? (
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 28, marginBottom: 4, transition: 'none' }}>{ICONS[picked.icon] || STAR}</div>
          <div style={{ fontSize: 16, fontWeight: 700, opacity: 0.4 }}>{picked.title}</div>
        </div>
      ) : (
        <div style={{ fontSize: 13, opacity: 0.5, marginBottom: 12 }}>
          {undone.length} habits left today. Can't decide?
        </div>
      )}
      <button
        onClick={doPick}
        disabled={animating}
        style={{
          padding: '10px 24px',
          borderRadius: 10,
          border: 'none',
          background: 'linear-gradient(135deg, #a78bfa, #7c3aed)',
          color: '#fff',
          fontWeight: 700,
          fontSize: 14,
          cursor: animating ? 'wait' : 'pointer',
          transition: 'all 0.2s',
        }}
      >
        {picked && !animating ? `${DICE} Pick again` : `${DICE} Pick for me`}
      </button>
    </div>
  );
}

function Heatmap({ heatmap, habits }: { heatmap: Record<string, string[]>; habits: Habit[] }) {
  const days = Object.keys(heatmap).sort();
  const total = habits.length;

  return (
    <div style={{
      background: 'var(--surface, #1a1a1a)',
      border: '1px solid var(--border, #333)',
      borderRadius: 12,
      padding: '14px 18px',
      marginBottom: 20,
    }}>
      <div style={{ fontSize: 12, fontWeight: 600, opacity: 0.5, marginBottom: 10, textTransform: 'uppercase', letterSpacing: 0.5 }}>
        Last 7 days
      </div>
      <div style={{ display: 'flex', gap: 6, justifyContent: 'space-between' }}>
        {days.map(day => {
          const done = heatmap[day].length;
          const ratio = total > 0 ? done / total : 0;
          const dayLabel = new Date(day + 'T12:00:00').toLocaleDateString('en', { weekday: 'short' });
          const isToday = day === days[days.length - 1];

          return (
            <div key={day} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4, flex: 1 }}>
              <div style={{
                width: '100%', maxWidth: 48, aspectRatio: '1', borderRadius: 8,
                background: done === 0
                  ? 'rgba(255,255,255,0.03)'
                  : ratio >= 1
                    ? 'rgba(74,222,128,0.5)'
                    : ratio >= 0.5
                      ? 'rgba(74,222,128,0.25)'
                      : 'rgba(74,222,128,0.1)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 13, fontWeight: 700, fontVariantNumeric: 'tabular-nums',
                color: done > 0 ? '#4ade80' : 'rgba(255,255,255,0.15)',
                border: isToday ? '2px solid rgba(74,222,128,0.4)' : '1px solid transparent',
              }}>
                {done}/{total}
              </div>
              <div style={{
                fontSize: 10, opacity: isToday ? 1 : 0.4,
                fontWeight: isToday ? 700 : 400,
              }}>
                {isToday ? 'Today' : dayLabel}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ProgressRing({ done, total }: { done: number; total: number }) {
  const pct = total > 0 ? done / total : 0;
  const r = 36;
  const circumference = 2 * Math.PI * r;
  const offset = circumference * (1 - pct);

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 20 }}>
      <svg width={84} height={84} style={{ flexShrink: 0 }}>
        <circle cx={42} cy={42} r={r} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth={6} />
        <circle
          cx={42} cy={42} r={r} fill="none"
          stroke={pct >= 1 ? '#4ade80' : pct > 0 ? '#a78bfa' : 'rgba(255,255,255,0.1)'}
          strokeWidth={6} strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          style={{ transition: 'stroke-dashoffset 0.5s ease', transform: 'rotate(-90deg)', transformOrigin: 'center' }}
        />
        <text x={42} y={42} textAnchor="middle" dominantBaseline="central"
          style={{ fontSize: 18, fontWeight: 800, fill: 'currentColor' }}>
          {done}/{total}
        </text>
      </svg>
      <div>
        <div style={{ fontSize: 18, fontWeight: 800 }}>
          {pct >= 1 ? 'Complete!' : pct > 0 ? 'Keep going' : 'Start your day'}
        </div>
        <div style={{ fontSize: 13, opacity: 0.5 }}>
          {pct >= 1
            ? 'All habits done today'
            : `${total - done} habit${total - done !== 1 ? 's' : ''} remaining`}
        </div>
      </div>
    </div>
  );
}

export function HabitsTab() {
  const { data, refetch } = useHabits(true);
  const [toggling, setToggling] = useState<string | null>(null);

  const handleToggle = useCallback(async (habitId: string) => {
    setToggling(habitId);
    try {
      await api.habitsToggle(habitId);
      await refetch();
    } catch (e) {
      console.error('Toggle failed:', e);
    } finally {
      setToggling(null);
    }
  }, [refetch]);

  if (!data) return <div className="empty">Loading habits...</div>;

  const { habits, heatmap, done_count, total_habits } = data as HabitsData;

  const undone = habits.filter(h => !h.done_today);
  const done = habits.filter(h => h.done_today);

  return (
    <div style={{ padding: '0 0 24px', maxWidth: 560, margin: '0 auto' }}>
      <div style={{ padding: '16px 0 8px' }}>
        <ProgressRing done={done_count} total={total_habits} />
      </div>

      <PickForMe habits={habits} onPick={() => {}} />

      <Heatmap heatmap={heatmap} habits={habits} />

      {undone.length > 0 && (
        <>
          <div style={{ fontSize: 11, fontWeight: 600, opacity: 0.4, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 8 }}>
            To do
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 20 }}>
            {undone.map(h => (
              <HabitCard key={h.id} habit={h} onToggle={() => handleToggle(h.id)} toggling={toggling === h.id} />
            ))}
          </div>
        </>
      )}

      {done.length > 0 && (
        <>
          <div style={{ fontSize: 11, fontWeight: 600, opacity: 0.4, textTransform: 'uppercase', letterSpacing: 0.5, marginBottom: 8 }}>
            Done
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {done.map(h => (
              <HabitCard key={h.id} habit={h} onToggle={() => handleToggle(h.id)} toggling={toggling === h.id} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
