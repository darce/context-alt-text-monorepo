import { useSyncExternalStore, type ReactNode } from 'react';

export type ClerkDoubleUser = {
  fullName?: string | null;
  primaryEmailAddress?: {
    emailAddress: string;
    verification?: { status: string };
  } | null;
};

export type ClerkDoubleState = {
  isLoaded: boolean;
  isSignedIn: boolean;
  userId: string | null;
  sessionId: string | null;
  user: ClerkDoubleUser | null;
  getToken: () => Promise<string | null>;
  signOut: (options?: { redirectUrl?: string }) => Promise<void>;
};

const listeners = new Set<() => void>();

function emitClerk() {
  for (const listener of listeners) {
    listener();
  }
}

function subscribeClerk(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

const initialState = (): ClerkDoubleState => ({
  isLoaded: true,
  isSignedIn: false,
  userId: null,
  sessionId: null,
  user: null,
  getToken: async () => null,
  signOut: async () => undefined,
});

export const clerkDouble: {
  state: ClerkDoubleState;
  reset: () => void;
  setState: (patch: Partial<ClerkDoubleState>) => void;
} = {
  state: initialState(),
  reset() {
    clerkDouble.state = initialState();
  },
  setState(patch: Partial<ClerkDoubleState>) {
    clerkDouble.state = { ...clerkDouble.state, ...patch };
    emitClerk();
  },
};

function getClerkSnapshot() {
  return clerkDouble.state;
}

export function ClerkProviderStub({ children }: { children?: ReactNode; publishableKey?: string }) {
  return children;
}

export function SignInStub() {
  return (
    <div role="form" aria-label="Secure account sign-in">
      Secure account sign-in
    </div>
  );
}

export function SignUpStub() {
  return (
    <div role="form" aria-label="Secure account setup">
      Secure account setup
    </div>
  );
}

export function UserButtonStub() {
  return (
    <button type="button" aria-label="Open account menu">
      Account
    </button>
  );
}

function stableGetToken() {
  return clerkDouble.state.getToken();
}

function stableSignOut(options?: { redirectUrl?: string }) {
  return clerkDouble.state.signOut(options);
}

export function useAuthStub() {
  const state = useSyncExternalStore(subscribeClerk, getClerkSnapshot, getClerkSnapshot);
  return {
    isLoaded: state.isLoaded,
    isSignedIn: state.isSignedIn,
    userId: state.userId,
    sessionId: state.sessionId,
    getToken: stableGetToken,
    signOut: stableSignOut,
  };
}

export function useUserStub() {
  const state = useSyncExternalStore(subscribeClerk, getClerkSnapshot, getClerkSnapshot);
  return {
    isLoaded: state.isLoaded,
    user: state.user,
  };
}
