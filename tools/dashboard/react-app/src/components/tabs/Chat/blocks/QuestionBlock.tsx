import { useState, useRef, useCallback } from 'react';
import { esc } from '@/lib/utils';
import { useChatContext } from '@/context/ChatContext';
import type { Block } from '@/context/ChatContext';

interface QuestionOption {
  label: string;
  description?: string;
}

interface Question {
  header?: string;
  question?: string;
  multiSelect?: boolean;
  options?: QuestionOption[];
}

export function QuestionBlock({ block }: { block: Block }) {
  const { socketRef, state } = useChatContext();
  const questions = (block.questions || []) as Question[];
  const [allAnswered, setAllAnswered] = useState(!!block.answered);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [answerLabels, setAnswerLabels] = useState<Record<string, string>>({});

  const handleQuestionAnswer = useCallback((qi: number, answer: string, label: string) => {
    const q = questions[qi];
    const questionText = q.question || `Question ${qi + 1}`;

    const newAnswers = { ...answers, [questionText]: answer };
    const newLabels = { ...answerLabels, [questionText]: label };
    setAnswers(newAnswers);
    setAnswerLabels(newLabels);

    // If all questions answered, send to backend
    if (Object.keys(newAnswers).length >= questions.length) {
      if (socketRef.current) {
        socketRef.current.emit('question_response', {
          answers: newAnswers,
          questions: questions,
          tab_id: state.tabId,
        });
      }
      setAllAnswered(true);
    }
  }, [answers, answerLabels, questions, socketRef, state.tabId]);

  return (
    <div className={`chat-question-wrapper${allAnswered ? ' chat-question-wrapper-answered' : ''}`}>
      {!allAnswered && (
        <div className="chat-question-badge">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10" />
            <path d="M9.09 9a3 3 0 015.83 1c0 2-3 3-3 3" />
            <line x1="12" y1="17" x2="12.01" y2="17" />
          </svg>
          Claude is asking {questions.length > 1 ? `${questions.length} questions` : 'a question'}
        </div>
      )}
      {allAnswered && (
        <div className="chat-question-answered-summary">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="20 6 9 17 4 12" />
          </svg>
          Answered: {Object.values(answerLabels).join('; ')}
        </div>
      )}
      {questions.map((q, qi) => {
        const questionText = q.question || `Question ${qi + 1}`;
        const isAnswered = questionText in answers;
        return (
          <SingleQuestion
            key={qi}
            question={q}
            disabled={isAnswered}
            answeredLabel={answerLabels[questionText]}
            onSubmit={(answer, label) => handleQuestionAnswer(qi, answer, label)}
          />
        );
      })}
    </div>
  );
}

function SingleQuestion({ question, onSubmit, disabled, answeredLabel }: {
  question: Question;
  onSubmit: (answer: string, label: string) => void;
  disabled?: boolean;
  answeredLabel?: string;
}) {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [otherActive, setOtherActive] = useState(false);
  const otherInputRef = useRef<HTMLInputElement>(null);
  const isMulti = question.multiSelect || false;
  const options = question.options || [];

  const handleOptionClick = (idx: string) => {
    if (isMulti) {
      setSelected(prev => {
        const next = new Set(prev);
        if (next.has(idx)) next.delete(idx); else next.add(idx);
        return next;
      });
    } else {
      setSelected(new Set([idx]));
    }
    if (idx === 'other') {
      setOtherActive(true);
      setTimeout(() => otherInputRef.current?.focus(), 0);
    } else if (!isMulti) {
      setOtherActive(false);
    }
  };

  const handleSubmit = () => {
    if (selected.size === 0) return;
    let answer = '';
    let label = '';
    if (selected.size === 1 && selected.has('other')) {
      answer = otherInputRef.current?.value || 'Other';
      label = answer;
    } else {
      const indices: string[] = [];
      const labels: string[] = [];
      for (const idx of selected) {
        if (idx === 'other') {
          indices.push(otherInputRef.current?.value || 'Other');
          labels.push(otherInputRef.current?.value || 'Other');
        } else {
          indices.push(options[Number(idx)]?.label || String(Number(idx) + 1));
          labels.push(options[Number(idx)]?.label || `Option ${Number(idx) + 1}`);
        }
      }
      answer = indices.join(',');
      label = labels.join(', ');
    }
    onSubmit(answer, label);
  };

  // Auto-submit on single-select click (not for "other")
  const handlePillClick = (idx: string) => {
    handleOptionClick(idx);
    if (!isMulti && idx !== 'other') {
      // Submit immediately for single-select
      const optIdx = Number(idx);
      const lbl = options[optIdx]?.label || `Option ${optIdx + 1}`;
      onSubmit(lbl, lbl);
    }
  };

  if (disabled) {
    return (
      <div className="chat-question chat-question-done">
        {question.question && (
          <div className="chat-question-text">{esc(question.question)}</div>
        )}
        <div className="chat-question-pills">
          <span className="chat-question-pill selected">{answeredLabel}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="chat-question">
      {question.question && (
        <div className="chat-question-text">{esc(question.question)}</div>
      )}
      <div className="chat-question-pills">
        {options.map((opt, oi) => (
          <button
            key={oi}
            className={`chat-question-pill${selected.has(String(oi)) ? ' selected' : ''}`}
            onClick={() => handlePillClick(String(oi))}
            title={opt.description || undefined}
          >
            {esc(opt.label)}
          </button>
        ))}
        <button
          className={`chat-question-pill chat-question-pill-other${selected.has('other') ? ' selected' : ''}`}
          onClick={() => handleOptionClick('other')}
        >
          Other...
        </button>
        {otherActive && (
          <input
            ref={otherInputRef}
            type="text"
            className="chat-question-other-input"
            placeholder="Type response..."
            onKeyDown={(e) => { if (e.key === 'Enter') handleSubmit(); }}
          />
        )}
      </div>
      {(isMulti || otherActive) && (
        <button
          className="chat-question-submit"
          disabled={selected.size === 0}
          onClick={handleSubmit}
        >
          Submit
        </button>
      )}
    </div>
  );
}
