import React from 'react';
import { __ } from '@wordpress/i18n';

interface Props {
  children: React.ReactNode;
  fallback?: React.ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends React.Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  handleRetry = (): void => {
    this.setState({ hasError: false, error: null });
  };

  render(): React.ReactNode {
    if (this.state.hasError) {
      return (
        this.props.fallback ?? (
          <div className="acx-error-boundary" role="alert">
            <p>{__('Something went wrong.', 'alt-context')}</p>
            <button type="button" className="button" onClick={this.handleRetry}>
              {__('Try again', 'alt-context')}
            </button>
          </div>
        )
      );
    }
    return this.props.children;
  }
}
