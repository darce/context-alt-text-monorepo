import type { ReactNode } from 'react';

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
  user: ClerkDoubleUser | null;
  getToken: () => Promise<string | null>;
  signOut: (options?: { redirectUrl?: string }) => Promise<void>;
};

const initialState = (): ClerkDoubleState => ({
  isLoaded: true,
  isSignedIn: false,
  userId: null,
  user: null,
  getToken: async () => null,
  signOut: async () => undefined,
});

export const clerkDouble: { state: ClerkDoubleState; reset: () => void } = {
  state: initialState(),
  reset() {
    clerkDouble.state = initialState();
  },
};

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
  return {
    isLoaded: clerkDouble.state.isLoaded,
    isSignedIn: clerkDouble.state.isSignedIn,
    userId: clerkDouble.state.userId,
    getToken: stableGetToken,
    signOut: stableSignOut,
  };
}

export function useUserStub() {
  return {
    isLoaded: clerkDouble.state.isLoaded,
    user: clerkDouble.state.user,
  };
}
