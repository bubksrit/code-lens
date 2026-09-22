import React, { useState, useEffect } from 'react';

interface HealthStatus {
  status: string;
}

export const App: React.FC = () => {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const checkHealth = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetch('/health');
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      const data: HealthStatus = await response.json();
      setHealth(data);
    } catch (err: any) {
      setError(err.message || 'Failed to connect to backend server');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    checkHealth();
  }, []);

  return (
    <div style={{ maxWidth: '900px', margin: '0 auto', padding: '2rem' }}>
      <header style={{ borderBottom: '1px solid #334155', paddingBottom: '1rem', marginBottom: '2rem' }}>
        <h1 style={{ color: '#38bdf8', marginBottom: '0.5rem' }}>PRISM Agentic Code Intelligence</h1>
        <p style={{ color: '#94a3b8', margin: 0 }}>
          Samsung PRISM Gen AI Hackathon 3.0 Theme 1 Prototype
        </p>
      </header>

      <main>
        <section
          style={{
            backgroundColor: '#1e293b',
            borderRadius: '8px',
            padding: '1.5rem',
            border: '1px solid #334155',
          }}
        >
          <h2 style={{ fontSize: '1.25rem', marginTop: 0, marginBottom: '1rem' }}>Backend Connection Status</h2>

          <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '1rem' }}>
            <button
              onClick={checkHealth}
              disabled={loading}
              style={{
                backgroundColor: '#0284c7',
                color: '#ffffff',
                border: 'none',
                padding: '0.5rem 1rem',
                borderRadius: '6px',
                cursor: 'pointer',
                fontWeight: 600,
              }}
            >
              {loading ? 'Checking...' : 'Check /health Status'}
            </button>
          </div>

          {health && (
            <div
              style={{
                padding: '1rem',
                backgroundColor: '#064e3b',
                color: '#6ee7b7',
                borderRadius: '6px',
                fontFamily: 'monospace',
              }}
            >
              Status: <strong>{health.status}</strong> (HTTP 200 OK)
            </div>
          )}

          {error && (
            <div
              style={{
                padding: '1rem',
                backgroundColor: '#7f1d1d',
                color: '#fca5a5',
                borderRadius: '6px',
                fontFamily: 'monospace',
              }}
            >
              Error: {error}
            </div>
          )}
        </section>
      </main>
    </div>
  );
};

export default App;
