import React from 'react';

interface ErrorPanelProps {
  title?: string;
  message?: string;
  onRetry?: () => void;
  lastAttempt?: Date | null;
  variant?: 'full' | 'inline';
}

export default function ErrorPanel({
  title = 'Something went wrong',
  message = 'An error occurred while loading data.',
  onRetry,
  lastAttempt,
  variant = 'full',
}: ErrorPanelProps) {
  const getRelativeTime = (date: Date) => {
    const diff = Math.floor((Date.now() - date.getTime()) / 1000);
    if (diff < 60) return 'just now';
    if (diff < 3600) return `${Math.floor(diff / 60)} minutes ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)} hours ago`;
    return `${Math.floor(diff / 86400)} days ago`;
  };

  const containerStyle: React.CSSProperties = {
    background: '#1e293b',
    border: '1px solid #ef4444',
    borderLeft: '3px solid #ef4444',
    borderRadius: '8px',
    padding: '20px 24px',
    ...(variant === 'full'
      ? { maxWidth: '480px', margin: '60px auto', textAlign: 'center' as const }
      : {}),
  };

  return (
    <div style={containerStyle} role="alert">
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          marginBottom: '8px',
          justifyContent: variant === 'full' ? 'center' : 'flex-start',
        }}
      >
        <span style={{ color: '#ef4444', fontSize: '20px' }}>&#9888;</span>
        <span style={{ color: '#ffffff', fontSize: '15px', fontWeight: 600 }}>
          {title}
        </span>
      </div>
      <p style={{ color: '#94a3b8', fontSize: '13px', margin: '0 0 16px 0' }}>
        {message}
      </p>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
          justifyContent: variant === 'full' ? 'center' : 'flex-start',
        }}
      >
        {onRetry && (
          <button
            onClick={onRetry}
            style={{
              background: '#3b82f6',
              color: 'white',
              border: 'none',
              borderRadius: '6px',
              padding: '8px 16px',
              cursor: 'pointer',
              fontSize: '13px',
              fontWeight: 500,
            }}
          >
            Retry
          </button>
        )}
        {lastAttempt && (
          <span style={{ color: '#64748b', fontSize: '11px' }}>
            Last attempt: {getRelativeTime(lastAttempt)}
          </span>
        )}
      </div>
    </div>
  );
}
