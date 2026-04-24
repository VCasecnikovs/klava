import { useState, useEffect, useRef } from 'react';
import { useChatContext } from '@/context/ChatContext';

const SPINNER_SYMBOLS = ['\u00b7', '\u273B', '\u273D', '\u2736', '\u2733', '\u2722'];

const SPINNER_PHRASES = [
  'Обкашляю вопросик', '10/10', 'Метнулся', 'Решаю вопросик',
  'Сейчас подскочу', 'За кофейчком метнусь', 'Шуршу в соцсетях',
  'Услышал тебя', 'Все чин чинарем', 'Он человечек хороший',
  'Кофейные вопросики обкашляем', 'Все я поскакал', 'Пошуршу по трендам',
  'Метнулся за трендами', 'Обкашляем новиночки', 'Пойдем по сигареточке',
  'Вопросик на контроле', 'Цифры знаешь - набирай', 'Дорогой мой человечек',
  'Человечек подскочит', 'Наберу на цифры', 'Водочки с нами выпьешь?',
  'Обрисуй персонажей', 'На подскоке', 'Дельце одно есть',
  'Человечек сориентирует', 'Двигаюсь в сторону центра', 'С центра уже двинул',
  'Вопросик этот вентилируй', 'Добро', 'Обнял-целую', 'Словимся',
  'Тема мутная', 'Чет не функционирует', 'Я на офисе', 'Обрисуй ситуацию',
  'Когда обед?', 'В выходной с двяками на шишлядос!', 'А ты парень смекалистый',
  'Абонент не абонент', 'Я на моторе', 'Уже трем за этот вопросик',
  'Здарова бандит', 'Фактурочку откройте', 'По красоте все сделаем',
  'Речь идет о трехзначных цифрах', 'Поставил дело на карандаш',
  'Тоси боси', 'Надо тему покачать', 'Евроденс', 'Все в ажуре',
  'Не отсвечивай', 'Отскочим - побормочем', 'Вопросик на тормозах',
  'Принял и понял', 'Все красиво, по предоплате', 'Все, бычкуюсь',
  'По незнанке сунулся', 'С тебя поляна', 'Не мороси',
  'За него человечки потянут', 'Скидочка будет?',
];

function formatElapsed(ms: number): string {
  const sec = Math.floor(ms / 1000);
  if (sec < 60) return `${sec}s`;
  return `${Math.floor(sec / 60)}m ${sec % 60}s`;
}

export function SpinnerBar() {
  const { state } = useChatContext();
  const { realtimeStatus, streamStart } = state;
  const [phraseIdx, setPhraseIdx] = useState(() => Math.floor(Math.random() * SPINNER_PHRASES.length));
  const [symbolIdx, setSymbolIdx] = useState(0);
  const [elapsed, setElapsed] = useState('0s');
  const [fading, setFading] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const phraseIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const symbolIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const isStreaming = realtimeStatus === 'streaming';

  useEffect(() => {
    if (!isStreaming) return;
    const start = streamStart || Date.now();
    const tick = () => setElapsed(formatElapsed(Date.now() - start));
    tick();
    intervalRef.current = setInterval(tick, 1000);
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, [isStreaming, streamStart]);

  // Symbol rotation - fast, like a spinner
  useEffect(() => {
    if (!isStreaming) return;
    symbolIntervalRef.current = setInterval(() => {
      setSymbolIdx(prev => (prev + 1) % SPINNER_SYMBOLS.length);
    }, 500);
    return () => { if (symbolIntervalRef.current) clearInterval(symbolIntervalRef.current); };
  }, [isStreaming]);

  // Phrase rotation - slow
  useEffect(() => {
    if (!isStreaming) return;
    phraseIntervalRef.current = setInterval(() => {
      setFading(true);
      setTimeout(() => {
        setPhraseIdx(prev => (prev + 1) % SPINNER_PHRASES.length);
        setFading(false);
      }, 400);
    }, 4000);
    return () => { if (phraseIntervalRef.current) clearInterval(phraseIntervalRef.current); };
  }, [isStreaming]);

  if (!isStreaming) return null;

  return (
    <div className="chat-spinner-bar">
      <span className="chat-spinner-symbol">{SPINNER_SYMBOLS[symbolIdx]}</span>
      <span className={`chat-spinner-phrase${fading ? ' fading' : ''}`}>
        {SPINNER_PHRASES[phraseIdx]}
      </span>
      <span className="chat-spinner-elapsed">{elapsed}</span>
    </div>
  );
}
