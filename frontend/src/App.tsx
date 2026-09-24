import React, { useState, useEffect } from 'react';
import {
  Code2,
  FlaskConical,
  Check,
  ChevronDown,
  ChevronRight,
  Loader2,
  ArrowRight,
  BookOpen,
  Clock,
  FileCode,
  Search,
  GitBranch,
  Eye,
} from 'lucide-react';

// ─── Data Contracts ────────────────────────────────────────────────────────

interface RepositoryItem {
  id: string;
  name: string;
  description?: string;
  path?: string;
}

interface ExecutionStep {
  step_number: number;
  tool_name: string;
  input_params: Record<string, unknown>;
  output_summary: string;
  reason: string;
  duration_ms: number;
}

interface EvidenceItem {
  evidence_id: string;
  kind: 'direct' | 'static_inference' | 'unresolved';
  file: string;
  start_line: number;
  end_line: number;
  symbol_id?: string;
  symbol_name?: string;
  source_text: string;
  description: string;
}

interface CallChainStep {
  order: number;
  symbol_id: string;
  symbol_name: string;
  qualified_name: string;
  file: string;
  start_line: number;
  end_line: number;
  role: string;
  edge_resolution?: string;
}

interface InvestigationResult {
  investigation_id: string;
  repository_id: string;
  question: string;
  answer_summary: string;
  call_chain: CallChainStep[];
  evidence: EvidenceItem[];
  trace: ExecutionStep[];
  validation_issues: string[];
  total_steps: number;
  latency_ms: number;
  grounding: string;
}

interface SimulationCaseResult {
  id: string;
  name: string;
  question: string;
  expected: string;
  actual: string;
  status: 'passed' | 'failed';
  duration_ms: number;
  diagnostic?: string;
  investigation_id?: string;
  call_chain_hops: number;
  evidence_count: number;
}

interface SimulationRunResult {
  repository_id: string;
  total: number;
  passed: number;
  failed: number;
  total_duration_ms: number;
  cases: SimulationCaseResult[];
}

interface HistoryItem {
  investigation_id: string;
  repository_id: string;
  repoName: string;
  question: string;
  timestamp: string;
  latency_ms: number;
  hops: number;
  evidence: number;
  result: InvestigationResult;
}

// ─── Design Tokens ──────────────────────────────────────────────────────────

const t = {
  bg: '#0d1117',
  surface: '#161b22',
  surfaceSubtle: '#11141a',
  border: '#30363d',
  borderSubtle: '#21262d',
  textPrimary: '#e6edf3',
  textSecondary: '#8b949e',
  textTertiary: '#6e7681',
  greenPrimary: '#238636',
  greenHover: '#2ea043',
  greenText: '#3fb950',
  greenBg: 'rgba(46, 160, 67, 0.10)',
  greenBorder: 'rgba(46, 160, 67, 0.30)',
  redText: '#f85149',
  redBg: 'rgba(248, 81, 73, 0.10)',
  redBorder: 'rgba(248, 81, 73, 0.30)',
  yellowText: '#d29922',
  yellowBg: 'rgba(210, 153, 34, 0.10)',
  yellowBorder: 'rgba(210, 153, 34, 0.30)',
  blueText: '#79c0ff',
  blueBg: 'rgba(121, 192, 255, 0.08)',
  blueBorder: 'rgba(121, 192, 255, 0.25)',
  neutralBtn: '#21262d',
  neutralBtnHover: '#30363d',
  codeFont: `'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace`,
  uiFont: `-apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans', Helvetica, Arial, sans-serif`,
};

const roleLabel: Record<string, string> = {
  entry_point: 'API Endpoint',
  auth: 'Auth / Security',
  service: 'Business Logic',
  repository: 'Data Access',
  database: 'Database',
  config: 'Configuration',
  error_handler: 'Error Handler',
  general: 'Function',
};

const roleStyle: Record<string, { bg: string; text: string; border: string }> = {
  entry_point:   { bg: '#1f2937', text: '#93c5fd', border: '#374151' },
  auth:          { bg: '#23153c', text: '#d8b4fe', border: '#3b1c6e' },
  service:       { bg: '#0e2a24', text: '#6ee7b7', border: '#164e40' },
  repository:    { bg: '#292112', text: '#fcd34d', border: '#4d3d1d' },
  database:      { bg: '#33121d', text: '#fda4af', border: '#5b1d31' },
  config:        { bg: '#1c2128', text: '#94a3b8', border: '#2d333b' },
  error_handler: { bg: '#281116', text: '#fca5a5', border: '#4c1d24' },
  general:       { bg: '#1c2128', text: '#c9d1d9', border: '#30363d' },
};

const toolIcon: Record<string, React.ReactNode> = {
  keyword_search: <Search size={12} />,
  symbol_lookup: <BookOpen size={12} />,
  find_callers: <GitBranch size={12} />,
  find_callees: <GitBranch size={12} />,
  get_source: <FileCode size={12} />,
  get_chunk: <FileCode size={12} />,
};

const toolReadable: Record<string, string> = {
  keyword_search: 'Searched for keywords',
  symbol_lookup: 'Looked up a symbol',
  find_callers: 'Found callers',
  find_callees: 'Traced to callees',
  get_source: 'Read source code',
  get_chunk: 'Read code chunk',
};

// ─── Helpers ────────────────────────────────────────────────────────────────

function shortFile(path: string): string {
  const parts = path.replace(/\\/g, '/').split('/');
  return parts.length > 2 ? parts.slice(-2).join('/') : path;
}

function pluralise(n: number, singular: string, plural?: string): string {
  return `${n} ${n === 1 ? singular : (plural ?? singular + 's')}`;
}

// ─── Sub-components ──────────────────────────────────────────────────────────

/** Visual horizontal call-path flow */
function CallPathFlow({ steps }: { steps: CallChainStep[] }) {
  if (steps.length === 0) return null;
  return (
    <div style={{ overflowX: 'auto', paddingBottom: '0.5rem' }}>
      <div style={{ display: 'flex', alignItems: 'stretch', gap: 0, minWidth: 'max-content' }}>
        {steps.map((step, idx) => {
          const style = roleStyle[step.role] || roleStyle.general;
          const label = roleLabel[step.role] || step.role;
          return (
            <React.Fragment key={step.symbol_id}>
              <div
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  padding: '0.6rem 0.9rem',
                  backgroundColor: style.bg,
                  border: `1px solid ${style.border}`,
                  borderRadius: '6px',
                  minWidth: '120px',
                  maxWidth: '160px',
                }}
              >
                <span
                  style={{
                    fontSize: '0.65rem',
                    fontWeight: 600,
                    color: style.text,
                    textTransform: 'uppercase',
                    letterSpacing: '0.05em',
                    marginBottom: '0.3rem',
                  }}
                >
                  {label}
                </span>
                <code
                  style={{
                    fontSize: '0.75rem',
                    color: t.textPrimary,
                    fontFamily: t.codeFont,
                    textAlign: 'center',
                    wordBreak: 'break-word',
                    lineHeight: 1.3,
                  }}
                >
                  {step.symbol_name}
                </code>
                <span
                  style={{
                    fontSize: '0.63rem',
                    color: t.textTertiary,
                    fontFamily: t.codeFont,
                    marginTop: '0.25rem',
                    textAlign: 'center',
                  }}
                >
                  {shortFile(step.file)}
                </span>
              </div>
              {idx < steps.length - 1 && (
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    padding: '0 0.3rem',
                    color: t.textTertiary,
                    flexShrink: 0,
                  }}
                >
                  <ArrowRight size={14} />
                </div>
              )}
            </React.Fragment>
          );
        })}
      </div>
    </div>
  );
}

/** Expandable evidence item */
function EvidenceCard({
  ev,
  expanded,
  onToggle,
}: {
  ev: EvidenceItem;
  expanded: boolean;
  onToggle: () => void;
}) {
  const isInferred = ev.kind !== 'direct';
  return (
    <div
      style={{
        border: `1px solid ${t.borderSubtle}`,
        borderLeft: `3px solid ${isInferred ? t.yellowText : t.greenText}`,
        borderRadius: '4px',
        overflow: 'hidden',
      }}
    >
      <button
        onClick={onToggle}
        style={{
          width: '100%',
          background: t.surfaceSubtle,
          border: 'none',
          padding: '0.65rem 0.85rem',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          cursor: 'pointer',
          gap: '0.5rem',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', minWidth: 0, flex: 1 }}>
          <FileCode size={13} color={isInferred ? t.yellowText : t.greenText} style={{ flexShrink: 0 }} />
          <div style={{ minWidth: 0 }}>
            <code style={{ fontSize: '0.8rem', color: t.textPrimary, fontFamily: t.codeFont }}>
              {shortFile(ev.file)}
            </code>
            <span style={{ fontSize: '0.75rem', color: t.textTertiary, marginLeft: '0.4rem' }}>
              lines {ev.start_line}–{ev.end_line}
            </span>
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexShrink: 0 }}>
          {ev.symbol_name && (
            <code style={{ fontSize: '0.72rem', color: t.textSecondary, fontFamily: t.codeFont }}>
              {ev.symbol_name}
            </code>
          )}
          {expanded ? <ChevronDown size={13} color={t.textTertiary} /> : <ChevronRight size={13} color={t.textTertiary} />}
        </div>
      </button>

      {expanded && (
        <div style={{ backgroundColor: t.bg, borderTop: `1px solid ${t.borderSubtle}` }}>
          {ev.description && (
            <div style={{ padding: '0.5rem 0.85rem', fontSize: '0.8rem', color: t.textSecondary, borderBottom: `1px solid ${t.borderSubtle}` }}>
              {ev.description}
            </div>
          )}
          {ev.source_text && (
            <pre
              style={{
                margin: 0,
                padding: '0.65rem 0.85rem',
                fontFamily: t.codeFont,
                fontSize: '0.75rem',
                color: t.textPrimary,
                overflowX: 'auto',
                whiteSpace: 'pre-wrap',
                lineHeight: 1.55,
              }}
            >
              {ev.source_text}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

// ─── How It Works Panel ─────────────────────────────────────────────────────

function HowItWorksPanel() {
  const steps = [
    { icon: <Search size={18} />, label: 'Choose a codebase', detail: 'Select the software project you want to understand.' },
    { icon: <BookOpen size={18} />, label: 'Ask a question', detail: 'Describe what you want to trace, find, or understand.' },
    { icon: <GitBranch size={18} />, label: 'Code Lens investigates', detail: 'It searches the code, traces function calls, and collects evidence.' },
    { icon: <Eye size={18} />, label: 'Review the answer', detail: 'See where the answer came from, with the actual code as proof.' },
  ];

  return (
    <div
      style={{
        backgroundColor: t.surface,
        border: `1px solid ${t.border}`,
        borderRadius: '8px',
        padding: '1.5rem',
        marginBottom: '2rem',
      }}
    >
      <h2 style={{ fontSize: '0.95rem', fontWeight: 600, margin: '0 0 1rem', color: t.textPrimary }}>
        How it works
      </h2>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '1rem' }}>
        {steps.map((s, i) => (
          <div key={i} style={{ display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: t.greenText }}>
              <span style={{ fontWeight: 700, fontSize: '0.75rem', minWidth: '1.2rem' }}>{i + 1}</span>
              {s.icon}
              <span style={{ fontSize: '0.85rem', fontWeight: 600, color: t.textPrimary }}>{s.label}</span>
            </div>
            <p style={{ fontSize: '0.8rem', color: t.textSecondary, margin: 0, lineHeight: 1.45, paddingLeft: '1.7rem' }}>
              {s.detail}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Main Component ─────────────────────────────────────────────────────────

const DEFAULT_QUESTION =
  'Trace an API request to the database write and identify where validation happens.';

export const App: React.FC = () => {
  const [repositories, setRepositories] = useState<RepositoryItem[]>([
    {
      id: 'demo_ecommerce',
      name: 'E-Commerce API',
      description: 'Handles product listings, customer orders, stock validation, and order persistence.',
    },
    {
      id: 'demo_auth',
      name: 'Authentication Service',
      description: 'Handles user login, credential verification, token issuance, and session management.',
    },
    {
      id: 'demo_tasks',
      name: 'Task Management API',
      description: 'Handles task creation, validation, retrieval, and status tracking.',
    },
    {
      id: 'demo_repo',
      name: 'Multi-Layer Python App',
      description: 'Multi-layer Python app demonstrating API routes, auth, services, repositories, and database operations.',
    },
  ]);
  const [repoId, setRepoId] = useState<string>('demo_ecommerce');
  const [question, setQuestion] = useState<string>(DEFAULT_QUESTION);

  // Execution states
  const [investigating, setInvestigating] = useState<boolean>(false);
  const [simulating, setSimulating] = useState<boolean>(false);
  const [errorMsg, setErrorMsg] = useState<{ title: string; detail: string } | null>(null);

  // Results
  const [investigationResult, setInvestigationResult] = useState<InvestigationResult | null>(null);
  const [simulationResult, setSimulationResult] = useState<SimulationRunResult | null>(null);

  // UI state
  const [showTechnicalDetails, setShowTechnicalDetails] = useState<boolean>(false);
  const [expandedEvidence, setExpandedEvidence] = useState<Set<string>>(new Set());
  const [expandedSimCase, setExpandedSimCase] = useState<Set<string>>(new Set());
  const [expandedTraceStep, setExpandedTraceStep] = useState<Set<number>>(new Set());
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [activeNav, setActiveNav] = useState<'investigate' | 'simulate' | 'history' | 'settings'>('investigate');
  const [showHowItWorks, setShowHowItWorks] = useState<boolean>(true);

  // Load registered repositories from backend on startup
  useEffect(() => {
    const loadRepositories = async () => {
      try {
        const resp = await fetch('/api/repositories');
        if (resp.ok) {
          const data = await resp.json();
          if (Array.isArray(data.items) && data.items.length > 0) {
            setRepositories(data.items);
            setRepoId(prev =>
              data.items.some((r: RepositoryItem) => r.id === prev) ? prev : data.items[0].id
            );
          } else if (Array.isArray(data.repositories) && data.repositories.length > 0) {
            const mapped = data.repositories.map((id: string) => ({ id, name: id }));
            setRepositories(mapped);
            setRepoId(prev =>
              mapped.some((r: RepositoryItem) => r.id === prev) ? prev : mapped[0].id
            );
          }
        }
      } catch (err) {
        console.warn('Unable to query repository registry from backend:', err);
      }
    };
    loadRepositories();
  }, []);

  const selectedRepo = repositories.find(r => r.id === repoId);

  // Default questions per repo
  const defaultQuestions: Record<string, string> = {
    demo_ecommerce: 'Trace an order creation request from the API endpoint to the database write.',
    demo_auth: 'Trace a user login request from the endpoint to credential verification.',
    demo_tasks: 'Trace a task creation request from the endpoint to the database write.',
    demo_repo: 'Trace an API request to the database write and identify where validation happens.',
  };

  const handleRepoChange = (id: string) => {
    setRepoId(id);
    setQuestion(defaultQuestions[id] || DEFAULT_QUESTION);
    setInvestigationResult(null);
    setSimulationResult(null);
    setErrorMsg(null);
  };

  // Handler: Investigate
  const handleInvestigate = async () => {
    if (!question.trim() || question.trim().length < 5) {
      setErrorMsg({
        title: 'Question too short',
        detail: 'Please enter a question with at least 5 characters.',
      });
      return;
    }

    setInvestigating(true);
    setErrorMsg(null);
    setSimulationResult(null);
    setExpandedEvidence(new Set());
    setShowTechnicalDetails(false);

    try {
      const resp = await fetch('/api/investigate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repository_id: repoId, question }),
      });

      if (!resp.ok) {
        const errBody = await resp.json().catch(() => ({}));
        if (resp.status === 422 || resp.status === 404) {
          throw new Error(
            `Codebase unavailable: ${errBody.detail || 'Unable to resolve the selected codebase.'}`
          );
        }
        throw new Error(errBody.detail || `Investigation failed with HTTP ${resp.status}`);
      }

      const data: InvestigationResult = await resp.json();
      setInvestigationResult(data);
      setActiveNav('investigate');

      // Add to session history
      setHistory(prev => [
        {
          investigation_id: data.investigation_id,
          repository_id: data.repository_id,
          repoName: selectedRepo?.name ?? data.repository_id,
          question: data.question,
          timestamp: new Date().toLocaleTimeString(),
          latency_ms: data.latency_ms,
          hops: data.call_chain.length,
          evidence: data.evidence.length,
          result: data,
        },
        ...prev.slice(0, 19),
      ]);
    } catch (err: unknown) {
      const msg =
        err instanceof Error ? err.message : 'An unexpected error occurred during investigation.';
      setErrorMsg({
        title: msg.startsWith('Codebase unavailable') ? 'Codebase unavailable' : 'Investigation failed',
        detail: msg.replace(/^Codebase unavailable:\s*|^Investigation failed:\s*/, ''),
      });
    } finally {
      setInvestigating(false);
    }
  };

  // Handler: Simulate
  const handleSimulate = async () => {
    setSimulating(true);
    setErrorMsg(null);
    setInvestigationResult(null);
    setExpandedSimCase(new Set());

    try {
      const resp = await fetch('/api/simulate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repository_id: repoId }),
      });

      if (!resp.ok) {
        const errBody = await resp.json().catch(() => ({}));
        throw new Error(errBody.detail || `Simulation failed with HTTP ${resp.status}`);
      }

      const data: SimulationRunResult = await resp.json();
      setSimulationResult(data);
      setActiveNav('simulate');
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Simulation suite failed to execute.';
      setErrorMsg({ title: 'Simulation failed', detail: msg });
    } finally {
      setSimulating(false);
    }
  };

  // ── Answer summary parser ──────────────────────────────────────────────────
  function renderAnswerSummary(text: string) {
    // Strip the **Repository:** and **Question:** meta lines — displayed separately
    const lines = text
      .split('\n')
      .filter(l => !l.startsWith('**Repository:**') && !l.startsWith('**Question:**'));

    return lines.map((line, idx) => {
      if (line.startsWith('**') && line.endsWith('**')) {
        return (
          <h4
            key={idx}
            style={{ fontSize: '0.9rem', fontWeight: 600, color: t.textPrimary, margin: '0.9rem 0 0.3rem' }}
          >
            {line.replace(/\*\*/g, '')}
          </h4>
        );
      }
      if (line.startsWith('  - ') || line.startsWith('- ')) {
        return (
          <div
            key={idx}
            style={{
              display: 'flex',
              gap: '0.5rem',
              marginLeft: '0.75rem',
              color: t.textSecondary,
              fontSize: '0.87rem',
              lineHeight: 1.5,
            }}
          >
            <span style={{ color: t.textTertiary, flexShrink: 0 }}>•</span>
            <span>{line.replace(/^\s*-\s*/, '')}</span>
          </div>
        );
      }
      if (!line.trim()) return <div key={idx} style={{ height: '0.45rem' }} />;
      return (
        <p key={idx} style={{ margin: '0.25rem 0', color: t.textSecondary, fontSize: '0.87rem', lineHeight: 1.55 }}>
          {line}
        </p>
      );
    });
  }

  // ── Nav button renderer ──────────────────────────────────────────────────
  function NavBtn({ id, label }: { id: typeof activeNav; label: string }) {
    return (
      <button
        onClick={() => setActiveNav(id)}
        style={{
          background: 'none',
          border: 'none',
          padding: '0.4rem 0.75rem',
          borderRadius: '6px',
          color: activeNav === id ? t.textPrimary : t.textSecondary,
          backgroundColor: activeNav === id ? t.borderSubtle : 'transparent',
          fontWeight: activeNav === id ? 600 : 400,
          fontSize: '0.85rem',
          cursor: 'pointer',
          transition: 'background-color 0.15s ease',
        }}
      >
        {label}
      </button>
    );
  }

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div style={{ backgroundColor: t.bg, minHeight: '100vh', fontFamily: t.uiFont, color: t.textPrimary }}>
      {/* ── Header ── */}
      <header
        style={{
          borderBottom: `1px solid ${t.border}`,
          backgroundColor: t.surface,
          padding: '0 1.5rem',
          height: '54px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          position: 'sticky',
          top: 0,
          zIndex: 100,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
          <div
            style={{
              width: '26px',
              height: '26px',
              borderRadius: '6px',
              backgroundColor: t.surfaceSubtle,
              border: `1px solid ${t.border}`,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: t.greenText,
            }}
          >
            <Code2 size={16} />
          </div>
          <span style={{ fontWeight: 600, fontSize: '0.95rem', letterSpacing: '-0.01em', color: t.textPrimary }}>
            Code Lens
          </span>
        </div>

        <nav style={{ display: 'flex', alignItems: 'center', gap: '0.15rem' }}>
          <NavBtn id="investigate" label="Investigate" />
          <NavBtn id="simulate" label="Simulate" />
          <NavBtn id="history" label="History" />
          <NavBtn id="settings" label="Settings" />
        </nav>
      </header>

      {/* ── Main ── */}
      <main style={{ maxWidth: '980px', margin: '0 auto', padding: '2rem 1.5rem' }}>

        {/* ══════════════════════ INVESTIGATE VIEW ══════════════════════ */}
        {activeNav === 'investigate' && (
          <>
            {/* Hero */}
            <div style={{ marginBottom: '2rem' }}>
              <h1
                style={{
                  fontSize: '1.5rem',
                  fontWeight: 700,
                  margin: 0,
                  color: t.textPrimary,
                  letterSpacing: '-0.02em',
                }}
              >
                Understand how a codebase works.
              </h1>
              <p style={{ fontSize: '0.92rem', color: t.textSecondary, margin: '0.45rem 0 0', lineHeight: 1.55 }}>
                Ask a question about a software project. Code Lens traces the relevant code and shows
                you where the answer came from.
              </p>
            </div>

            {/* How it works (dismissible) */}
            {showHowItWorks && !investigationResult && !simulationResult && (
              <div style={{ position: 'relative' }}>
                <HowItWorksPanel />
                <button
                  onClick={() => setShowHowItWorks(false)}
                  style={{
                    position: 'absolute',
                    top: '1.1rem',
                    right: '1.1rem',
                    background: 'none',
                    border: 'none',
                    color: t.textTertiary,
                    fontSize: '0.75rem',
                    cursor: 'pointer',
                  }}
                >
                  Dismiss
                </button>
              </div>
            )}

            {/* Input panel */}
            <div
              style={{
                backgroundColor: t.surface,
                border: `1px solid ${t.border}`,
                borderRadius: '8px',
                padding: '1.5rem',
                marginBottom: '1.5rem',
              }}
            >
              {/* Codebase selector */}
              <div style={{ marginBottom: '1.25rem' }}>
                <label
                  style={{
                    display: 'block',
                    fontSize: '0.82rem',
                    fontWeight: 600,
                    color: t.textSecondary,
                    marginBottom: '0.4rem',
                    textTransform: 'uppercase',
                    letterSpacing: '0.04em',
                  }}
                >
                  Codebase
                </label>
                <select
                  value={repoId}
                  onChange={e => handleRepoChange(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '0.55rem 0.75rem',
                    backgroundColor: t.surfaceSubtle,
                    border: `1px solid ${t.border}`,
                    borderRadius: '6px',
                    color: t.textPrimary,
                    fontSize: '0.9rem',
                    outline: 'none',
                    cursor: 'pointer',
                  }}
                >
                  {repositories.map(repo => (
                    <option key={repo.id} value={repo.id}>
                      {repo.name}
                    </option>
                  ))}
                </select>
                <p style={{ fontSize: '0.77rem', color: t.textTertiary, margin: '0.3rem 0 0', lineHeight: 1.4 }}>
                  {selectedRepo?.description ?? 'Code Lens will only search the codebase you select.'}
                </p>
              </div>

              {/* Question */}
              <div style={{ marginBottom: '1.25rem' }}>
                <label
                  style={{
                    display: 'block',
                    fontSize: '0.82rem',
                    fontWeight: 600,
                    color: t.textSecondary,
                    marginBottom: '0.4rem',
                    textTransform: 'uppercase',
                    letterSpacing: '0.04em',
                  }}
                >
                  What do you want to understand?
                </label>
                <textarea
                  value={question}
                  onChange={e => setQuestion(e.target.value)}
                  placeholder="e.g. Trace an API request to the database write and identify where validation happens."
                  rows={3}
                  style={{
                    width: '100%',
                    boxSizing: 'border-box',
                    padding: '0.65rem 0.75rem',
                    backgroundColor: t.surfaceSubtle,
                    border: `1px solid ${t.border}`,
                    borderRadius: '6px',
                    color: t.textPrimary,
                    fontSize: '0.9rem',
                    lineHeight: 1.5,
                    resize: 'vertical',
                    outline: 'none',
                    fontFamily: t.uiFont,
                  }}
                />
                <p style={{ fontSize: '0.77rem', color: t.textTertiary, margin: '0.3rem 0 0', lineHeight: 1.4 }}>
                  Ask about how something works, where something happens, or how two parts of the
                  application are connected.
                </p>
              </div>

              {/* Actions */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.2rem' }}>
                  <button
                    onClick={handleInvestigate}
                    disabled={investigating || simulating}
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '0.45rem',
                      padding: '0.55rem 1.25rem',
                      backgroundColor: investigating ? '#195a25' : t.greenPrimary,
                      color: '#ffffff',
                      border: '1px solid rgba(240,246,252,0.1)',
                      borderRadius: '6px',
                      fontWeight: 600,
                      fontSize: '0.9rem',
                      cursor: investigating || simulating ? 'not-allowed' : 'pointer',
                      opacity: investigating || simulating ? 0.75 : 1,
                      transition: 'background-color 0.15s ease',
                    }}
                  >
                    {investigating ? (
                      <>
                        <Loader2 size={15} className="animate-spin" />
                        <span>Tracing your question through the codebase…</span>
                      </>
                    ) : (
                      <span>Investigate</span>
                    )}
                  </button>
                  {!investigating && (
                    <span style={{ fontSize: '0.72rem', color: t.textTertiary }}>
                      Answer one question about the selected codebase.
                    </span>
                  )}
                </div>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.2rem' }}>
                  <button
                    onClick={handleSimulate}
                    disabled={investigating || simulating}
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: '0.45rem',
                      padding: '0.55rem 1.15rem',
                      backgroundColor: t.neutralBtn,
                      color: t.textPrimary,
                      border: `1px solid ${t.border}`,
                      borderRadius: '6px',
                      fontWeight: 500,
                      fontSize: '0.9rem',
                      cursor: investigating || simulating ? 'not-allowed' : 'pointer',
                      opacity: investigating || simulating ? 0.75 : 1,
                      transition: 'background-color 0.15s ease',
                    }}
                  >
                    {simulating ? (
                      <>
                        <Loader2 size={15} className="animate-spin" />
                        <span>Running questions…</span>
                      </>
                    ) : (
                      <>
                        <FlaskConical size={14} color={t.textSecondary} />
                        <span>Simulate</span>
                      </>
                    )}
                  </button>
                  {!simulating && (
                    <span style={{ fontSize: '0.72rem', color: t.textTertiary }}>
                      Run several predefined questions to test Code Lens.
                    </span>
                  )}
                </div>
              </div>
            </div>

            {/* Error banner */}
            {errorMsg && (
              <div
                style={{
                  marginBottom: '1.5rem',
                  padding: '0.85rem 1rem',
                  backgroundColor: t.redBg,
                  border: `1px solid ${t.redBorder}`,
                  borderRadius: '6px',
                }}
              >
                <div style={{ fontSize: '0.88rem', fontWeight: 600, color: t.redText }}>
                  {errorMsg.title}
                </div>
                <div style={{ fontSize: '0.82rem', color: '#fca5a5', marginTop: '0.2rem' }}>
                  {errorMsg.detail}
                </div>
              </div>
            )}

            {/* ── Investigation Result ── */}
            {investigationResult && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '1.25rem' }}>

                {/* Status bar */}
                <div
                  style={{
                    backgroundColor: t.surface,
                    border: `1px solid ${t.border}`,
                    borderRadius: '8px',
                    padding: '1rem 1.25rem',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    flexWrap: 'wrap',
                    gap: '0.75rem',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem' }}>
                    <span
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '0.3rem',
                        padding: '0.2rem 0.55rem',
                        borderRadius: '4px',
                        backgroundColor: t.greenBg,
                        border: `1px solid ${t.greenBorder}`,
                        color: t.greenText,
                        fontSize: '0.75rem',
                        fontWeight: 600,
                      }}
                    >
                      <Check size={11} />
                      Analysis complete
                    </span>
                    <span style={{ fontSize: '0.82rem', color: t.textSecondary }}>
                      {pluralise(investigationResult.call_chain.length, 'step')} traced ·{' '}
                      {pluralise(investigationResult.total_steps, 'code search', 'code searches')} ·{' '}
                      {pluralise(investigationResult.evidence.length, 'supporting code reference')} ·{' '}
                      {investigationResult.latency_ms.toFixed(0)} ms
                    </span>
                  </div>
                  <div style={{ fontSize: '0.77rem', color: t.textTertiary }}>
                    Codebase:{' '}
                    <code style={{ fontFamily: t.codeFont, color: t.textSecondary }}>
                      {selectedRepo?.name ?? investigationResult.repository_id}
                    </code>
                  </div>
                </div>

                {/* What Code Lens found */}
                <div
                  style={{
                    backgroundColor: t.surface,
                    border: `1px solid ${t.border}`,
                    borderRadius: '8px',
                    padding: '1.5rem',
                  }}
                >
                  <h2 style={{ fontSize: '1.05rem', fontWeight: 600, margin: '0 0 0.25rem', color: t.textPrimary }}>
                    What Code Lens found
                  </h2>
                  <p style={{ fontSize: '0.78rem', color: t.textTertiary, margin: '0 0 1rem' }}>
                    Based on tracing through {selectedRepo?.name ?? investigationResult.repository_id}
                  </p>
                  <div>{renderAnswerSummary(investigationResult.answer_summary)}</div>
                </div>

                {/* How it works — visual code path */}
                {investigationResult.call_chain.length > 0 && (
                  <div
                    style={{
                      backgroundColor: t.surface,
                      border: `1px solid ${t.border}`,
                      borderRadius: '8px',
                      padding: '1.25rem 1.5rem',
                    }}
                  >
                    <h3 style={{ fontSize: '0.95rem', fontWeight: 600, margin: '0 0 0.9rem', color: t.textPrimary }}>
                      How it works
                    </h3>
                    <CallPathFlow steps={investigationResult.call_chain} />
                  </div>
                )}

                {/* Supporting code */}
                {investigationResult.evidence.length > 0 && (
                  <div
                    style={{
                      backgroundColor: t.surface,
                      border: `1px solid ${t.border}`,
                      borderRadius: '8px',
                      padding: '1.25rem 1.5rem',
                    }}
                  >
                    <h3 style={{ fontSize: '0.95rem', fontWeight: 600, margin: '0 0 0.2rem', color: t.textPrimary }}>
                      Supporting code
                    </h3>
                    <p style={{ fontSize: '0.78rem', color: t.textTertiary, margin: '0 0 0.9rem' }}>
                      The actual files Code Lens read to build this answer. Click any row to see the
                      code.
                    </p>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                      {investigationResult.evidence.map(ev => (
                        <EvidenceCard
                          key={ev.evidence_id}
                          ev={ev}
                          expanded={expandedEvidence.has(ev.evidence_id)}
                          onToggle={() => {
                            setExpandedEvidence(prev => {
                              const next = new Set(prev);
                              next.has(ev.evidence_id) ? next.delete(ev.evidence_id) : next.add(ev.evidence_id);
                              return next;
                            });
                          }}
                        />
                      ))}
                    </div>
                  </div>
                )}

                {/* Technical details (expandable) */}
                <div
                  style={{
                    backgroundColor: t.surface,
                    border: `1px solid ${t.border}`,
                    borderRadius: '8px',
                    overflow: 'hidden',
                  }}
                >
                  <button
                    onClick={() => setShowTechnicalDetails(prev => !prev)}
                    style={{
                      width: '100%',
                      background: 'none',
                      border: 'none',
                      padding: '0.85rem 1.25rem',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      cursor: 'pointer',
                      color: t.textSecondary,
                    }}
                  >
                    <span style={{ fontSize: '0.85rem', fontWeight: 600 }}>Technical details</span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.75rem', color: t.textTertiary }}>
                      <span>{investigationResult.trace.length} tool calls</span>
                      {showTechnicalDetails ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                    </div>
                  </button>

                  {showTechnicalDetails && (
                    <div
                      style={{
                        borderTop: `1px solid ${t.borderSubtle}`,
                        padding: '0.75rem 1.25rem 1.25rem',
                      }}
                    >
                      <div
                        style={{
                          fontSize: '0.75rem',
                          color: t.textTertiary,
                          marginBottom: '0.75rem',
                          fontFamily: t.codeFont,
                        }}
                      >
                        Run ID: {investigationResult.investigation_id} · Grounding: {investigationResult.grounding}
                      </div>

                      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.35rem' }}>
                        {investigationResult.trace.map(st => {
                          const isExp = expandedTraceStep.has(st.step_number);
                          return (
                            <div
                              key={st.step_number}
                              style={{ border: `1px solid ${t.borderSubtle}`, borderRadius: '5px', overflow: 'hidden' }}
                            >
                              <div
                                onClick={() => {
                                  setExpandedTraceStep(prev => {
                                    const next = new Set(prev);
                                    next.has(st.step_number) ? next.delete(st.step_number) : next.add(st.step_number);
                                    return next;
                                  });
                                }}
                                style={{
                                  display: 'flex',
                                  alignItems: 'center',
                                  gap: '0.6rem',
                                  padding: '0.45rem 0.75rem',
                                  backgroundColor: t.surfaceSubtle,
                                  cursor: 'pointer',
                                }}
                              >
                                <span style={{ fontSize: '0.7rem', color: t.textTertiary, width: '18px', flexShrink: 0 }}>
                                  #{st.step_number}
                                </span>
                                <span style={{ color: t.greenText, display: 'flex', alignItems: 'center' }}>
                                  {toolIcon[st.tool_name] ?? <Search size={12} />}
                                </span>
                                <span style={{ fontSize: '0.78rem', color: t.textSecondary, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                  {toolReadable[st.tool_name] ?? st.tool_name}: {st.reason}
                                </span>
                                <span style={{ fontSize: '0.7rem', color: t.textTertiary, fontFamily: t.codeFont, flexShrink: 0 }}>
                                  {st.duration_ms.toFixed(1)} ms
                                </span>
                                {isExp ? <ChevronDown size={12} color={t.textTertiary} /> : <ChevronRight size={12} color={t.textTertiary} />}
                              </div>
                              {isExp && (
                                <div
                                  style={{
                                    padding: '0.5rem 0.75rem',
                                    backgroundColor: t.bg,
                                    borderTop: `1px solid ${t.borderSubtle}`,
                                    fontSize: '0.75rem',
                                  }}
                                >
                                  <div style={{ color: t.textTertiary, marginBottom: '0.2rem' }}>Input:</div>
                                  <pre style={{ margin: '0 0 0.4rem', fontFamily: t.codeFont, color: t.textPrimary, whiteSpace: 'pre-wrap' }}>
                                    {JSON.stringify(st.input_params, null, 2)}
                                  </pre>
                                  <div style={{ color: t.textTertiary, marginBottom: '0.2rem' }}>Output:</div>
                                  <div style={{ color: t.textSecondary }}>{st.output_summary}</div>
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}
          </>
        )}

        {/* ══════════════════════ SIMULATE VIEW ══════════════════════ */}
        {activeNav === 'simulate' && (
          <div>
            <div style={{ marginBottom: '1.75rem' }}>
              <h1 style={{ fontSize: '1.35rem', fontWeight: 700, margin: 0, letterSpacing: '-0.01em' }}>
                Simulate
              </h1>
              <p style={{ fontSize: '0.9rem', color: t.textSecondary, margin: '0.4rem 0 0', lineHeight: 1.5 }}>
                We'll ask Code Lens several questions about the selected codebase and check whether it finds the expected parts of the application.
              </p>
            </div>

            {/* Codebase picker for simulate */}
            <div
              style={{
                backgroundColor: t.surface,
                border: `1px solid ${t.border}`,
                borderRadius: '8px',
                padding: '1.25rem 1.5rem',
                marginBottom: '1.5rem',
              }}
            >
              <div style={{ marginBottom: '1rem' }}>
                <label
                  style={{
                    display: 'block',
                    fontSize: '0.82rem',
                    fontWeight: 600,
                    color: t.textSecondary,
                    marginBottom: '0.4rem',
                    textTransform: 'uppercase',
                    letterSpacing: '0.04em',
                  }}
                >
                  Codebase
                </label>
                <select
                  value={repoId}
                  onChange={e => handleRepoChange(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '0.55rem 0.75rem',
                    backgroundColor: t.surfaceSubtle,
                    border: `1px solid ${t.border}`,
                    borderRadius: '6px',
                    color: t.textPrimary,
                    fontSize: '0.9rem',
                    outline: 'none',
                    cursor: 'pointer',
                  }}
                >
                  {repositories.map(repo => (
                    <option key={repo.id} value={repo.id}>
                      {repo.name}
                    </option>
                  ))}
                </select>
              </div>
              <button
                onClick={handleSimulate}
                disabled={simulating || investigating}
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '0.45rem',
                  padding: '0.55rem 1.25rem',
                  backgroundColor: simulating ? '#195a25' : t.greenPrimary,
                  color: '#ffffff',
                  border: '1px solid rgba(240,246,252,0.1)',
                  borderRadius: '6px',
                  fontWeight: 600,
                  fontSize: '0.9rem',
                  cursor: simulating || investigating ? 'not-allowed' : 'pointer',
                  opacity: simulating || investigating ? 0.75 : 1,
                }}
              >
                {simulating ? (
                  <>
                    <Loader2 size={15} className="animate-spin" />
                    <span>Running questions…</span>
                  </>
                ) : (
                  <>
                    <FlaskConical size={14} />
                    <span>Run Simulation</span>
                  </>
                )}
              </button>
            </div>

            {/* Error */}
            {errorMsg && (
              <div
                style={{
                  marginBottom: '1.5rem',
                  padding: '0.85rem 1rem',
                  backgroundColor: t.redBg,
                  border: `1px solid ${t.redBorder}`,
                  borderRadius: '6px',
                }}
              >
                <div style={{ fontSize: '0.88rem', fontWeight: 600, color: t.redText }}>{errorMsg.title}</div>
                <div style={{ fontSize: '0.82rem', color: '#fca5a5', marginTop: '0.2rem' }}>{errorMsg.detail}</div>
              </div>
            )}

            {/* Simulation results */}
            {simulationResult && (
              <div
                style={{
                  backgroundColor: t.surface,
                  border: `1px solid ${t.border}`,
                  borderRadius: '8px',
                  overflow: 'hidden',
                }}
              >
                {/* Header */}
                <div
                  style={{
                    padding: '1rem 1.5rem',
                    borderBottom: `1px solid ${t.borderSubtle}`,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    flexWrap: 'wrap',
                    gap: '0.75rem',
                  }}
                >
                  <div>
                    <div style={{ fontWeight: 600, fontSize: '1rem' }}>
                      {selectedRepo?.name ?? simulationResult.repository_id}
                    </div>
                    <div style={{ fontSize: '0.8rem', color: t.textSecondary, marginTop: '0.15rem' }}>
                      {pluralise(simulationResult.total, 'question')} tested ·{' '}
                      {simulationResult.total_duration_ms.toFixed(0)} ms total
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: '1rem', fontSize: '0.88rem' }}>
                    <span style={{ color: t.greenText, fontWeight: 600 }}>
                      ✓ {simulationResult.passed} passed
                    </span>
                    {simulationResult.failed > 0 && (
                      <span style={{ color: t.redText, fontWeight: 600 }}>
                        ✕ {simulationResult.failed} failed
                      </span>
                    )}
                  </div>
                </div>

                {/* Cases */}
                <div style={{ display: 'flex', flexDirection: 'column' }}>
                  {simulationResult.cases.map((c, idx) => {
                    const isExp = expandedSimCase.has(c.id);
                    const passed = c.status === 'passed';
                    return (
                      <div
                        key={c.id}
                        style={{
                          borderTop: idx === 0 ? 'none' : `1px solid ${t.borderSubtle}`,
                        }}
                      >
                        <button
                          onClick={() => {
                            setExpandedSimCase(prev => {
                              const next = new Set(prev);
                              next.has(c.id) ? next.delete(c.id) : next.add(c.id);
                              return next;
                            });
                          }}
                          style={{
                            width: '100%',
                            background: isExp ? t.surfaceSubtle : 'transparent',
                            border: 'none',
                            padding: '0.85rem 1.5rem',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.9rem',
                            cursor: 'pointer',
                            textAlign: 'left',
                          }}
                        >
                          <span
                            style={{
                              fontSize: '0.78rem',
                              fontWeight: 700,
                              color: passed ? t.greenText : t.redText,
                              minWidth: '60px',
                            }}
                          >
                            {passed ? '✓ Pass' : '✕ Fail'}
                          </span>
                          <div style={{ flex: 1, minWidth: 0 }}>
                            <div style={{ fontSize: '0.88rem', fontWeight: 500, color: t.textPrimary, marginBottom: '0.15rem' }}>
                              {c.name}
                            </div>
                            <div
                              style={{
                                fontSize: '0.77rem',
                                color: t.textSecondary,
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                                whiteSpace: 'nowrap',
                              }}
                            >
                              {c.question}
                            </div>
                          </div>
                          <div style={{ fontSize: '0.75rem', color: t.textTertiary, flexShrink: 0, textAlign: 'right' }}>
                            <div>
                              Found: {pluralise(c.evidence_count, 'supporting file')}
                            </div>
                            <div>{pluralise(c.call_chain_hops, 'step')} traced</div>
                          </div>
                          {isExp ? (
                            <ChevronDown size={14} color={t.textTertiary} />
                          ) : (
                            <ChevronRight size={14} color={t.textTertiary} />
                          )}
                        </button>

                        {isExp && (
                          <div
                            style={{
                              padding: '0.75rem 1.5rem 1rem',
                              backgroundColor: t.surfaceSubtle,
                              borderTop: `1px solid ${t.borderSubtle}`,
                            }}
                          >
                            <div style={{ fontSize: '0.82rem', color: t.textSecondary, marginBottom: '0.3rem' }}>
                              <strong style={{ color: t.textPrimary }}>Question:</strong>{' '}
                              {c.question}
                            </div>
                            <div style={{ fontSize: '0.82rem', marginBottom: '0.3rem' }}>
                              <strong style={{ color: t.textPrimary }}>Expected:</strong>{' '}
                              <span style={{ color: t.textSecondary }}>{c.expected}</span>
                            </div>
                            <div style={{ fontSize: '0.82rem', marginBottom: c.diagnostic ? '0.3rem' : 0 }}>
                              <strong style={{ color: t.textPrimary }}>Result:</strong>{' '}
                              <span style={{ color: passed ? t.greenText : t.redText }}>{c.actual}</span>
                            </div>
                            {c.diagnostic && (
                              <div style={{ fontSize: '0.77rem', color: t.textTertiary, marginTop: '0.25rem' }}>
                                {c.diagnostic}
                              </div>
                            )}
                            <div style={{ fontSize: '0.72rem', color: t.textTertiary, marginTop: '0.4rem', fontFamily: t.codeFont }}>
                              {c.duration_ms.toFixed(0)} ms
                              {c.investigation_id && ` · Run ID: ${c.investigation_id}`}
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ══════════════════════ HISTORY VIEW ══════════════════════ */}
        {activeNav === 'history' && (
          <div>
            <div style={{ marginBottom: '1.75rem' }}>
              <h1 style={{ fontSize: '1.35rem', fontWeight: 700, margin: 0, letterSpacing: '-0.01em' }}>
                History
              </h1>
              <p style={{ fontSize: '0.9rem', color: t.textSecondary, margin: '0.4rem 0 0' }}>
                Recent investigations run during this session.
              </p>
            </div>

            {history.length === 0 ? (
              <div
                style={{
                  backgroundColor: t.surface,
                  border: `1px solid ${t.border}`,
                  borderRadius: '8px',
                  padding: '3rem',
                  textAlign: 'center',
                  color: t.textSecondary,
                  fontSize: '0.88rem',
                }}
              >
                No investigations yet. Run an investigation first.
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                {history.map(item => (
                  <button
                    key={item.investigation_id}
                    onClick={() => {
                      setRepoId(item.repository_id);
                      setQuestion(item.question);
                      setInvestigationResult(item.result);
                      setActiveNav('investigate');
                    }}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: '0.85rem 1.1rem',
                      backgroundColor: t.surface,
                      border: `1px solid ${t.border}`,
                      borderRadius: '8px',
                      cursor: 'pointer',
                      textAlign: 'left',
                      width: '100%',
                    }}
                  >
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div
                        style={{
                          fontSize: '0.88rem',
                          fontWeight: 500,
                          color: t.textPrimary,
                          marginBottom: '0.2rem',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {item.question}
                      </div>
                      <div style={{ fontSize: '0.76rem', color: t.textSecondary, display: 'flex', gap: '0.6rem', flexWrap: 'wrap' }}>
                        <span>{item.repoName}</span>
                        <span>·</span>
                        <span>{pluralise(item.hops, 'step')} traced</span>
                        <span>·</span>
                        <span>{pluralise(item.evidence, 'supporting file')}</span>
                        <span>·</span>
                        <span>{item.latency_ms.toFixed(0)} ms</span>
                      </div>
                    </div>
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '0.4rem',
                        fontSize: '0.76rem',
                        color: t.textTertiary,
                        flexShrink: 0,
                        marginLeft: '1rem',
                      }}
                    >
                      <Clock size={12} />
                      {item.timestamp}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ══════════════════════ SETTINGS VIEW ══════════════════════ */}
        {activeNav === 'settings' && (
          <div>
            <div style={{ marginBottom: '1.75rem' }}>
              <h1 style={{ fontSize: '1.35rem', fontWeight: 700, margin: 0, letterSpacing: '-0.01em' }}>
                Settings
              </h1>
              <p style={{ fontSize: '0.9rem', color: t.textSecondary, margin: '0.4rem 0 0' }}>
                Codebases available for investigation and simulation.
              </p>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
              {repositories.map(repo => (
                <div
                  key={repo.id}
                  style={{
                    backgroundColor: t.surface,
                    border: `1px solid ${t.border}`,
                    borderRadius: '8px',
                    padding: '1rem 1.25rem',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.3rem' }}>
                    <span style={{ fontWeight: 600, fontSize: '0.92rem', color: t.textPrimary }}>
                      {repo.name}
                    </span>
                    <code
                      style={{
                        fontSize: '0.72rem',
                        padding: '0.1rem 0.4rem',
                        backgroundColor: t.borderSubtle,
                        borderRadius: '4px',
                        color: t.textSecondary,
                        fontFamily: t.codeFont,
                      }}
                    >
                      {repo.id}
                    </code>
                  </div>
                  {repo.description && (
                    <div style={{ fontSize: '0.82rem', color: t.textSecondary, marginBottom: '0.35rem' }}>
                      {repo.description}
                    </div>
                  )}
                  {repo.path && (
                    <div style={{ fontSize: '0.73rem', color: t.textTertiary, fontFamily: t.codeFont }}>
                      {repo.path}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </main>
    </div>
  );
};

export default App;
