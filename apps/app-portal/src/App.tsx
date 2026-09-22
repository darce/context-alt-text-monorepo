import { ClerkProvider, SignIn, SignUp, UserButton, useAuth, useUser } from '@clerk/react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { fetchPortalMe, PortalMeOutcome, type PortalMeResult } from './api/portalMe';
import { readPortalConfig, type PortalRuntimeConfig } from './config';
import { AccountScreen } from './screens/AccountScreen';
import { LogoutScreen } from './screens/LogoutScreen';
import { NotAdmittedScreen } from './screens/NotAdmittedScreen';
import { OutageScreen } from './screens/OutageScreen';
import { SignInScreen } from './screens/SignInScreen';
import { SignUpScreen } from './screens/SignUpScreen';
import { SignedOutScreen } from './screens/SignedOutScreen';
import { UnavailableScreen } from './screens/UnavailableScreen';

export type AppProps = {
  config?: PortalRuntimeConfig;
  fetchImpl?: typeof fetch;
  clerkLoadTimeoutMs?: number;
  portalMeTimeoutMs?: number;
};

type AccountOwner = {
  userId: string;
  sessionId: string;
};

type AccountView =
  | { status: 'idle' }
  | { status: 'loading'; owner: AccountOwner }
  | { status: 'ok'; tenantId: string; owner: AccountOwner }
  | { status: 'empty'; owner: AccountOwner }
  | { status: 'unauthorized'; owner: AccountOwner }
  | { status: 'email_unverified'; owner: AccountOwner }
  | { status: 'not_admitted'; owner: AccountOwner }
  | { status: 'outage'; owner: AccountOwner };

type LogoutView = 'idle' | 'loading' | 'error';

const CLERK_LOAD_TIMEOUT_MS = 8_000;

function isEmailVerified(user: ReturnType<typeof useUser>['user']): boolean {
  const status = user?.primaryEmailAddress?.verification?.status;
  return status === 'verified';
}

function personName(user: ReturnType<typeof useUser>['user']): string | null {
  const name = user?.fullName?.trim();
  return name ? name : null;
}

function readOwner(userId: string | null | undefined, sessionId: string | null | undefined): AccountOwner | null {
  if (!userId) {
    return null;
  }
  return { userId, sessionId: sessionId ?? '' };
}

function ownersMatch(left: AccountOwner | null | undefined, right: AccountOwner | null | undefined): boolean {
  return Boolean(left && right && left.userId === right.userId && left.sessionId === right.sessionId);
}

function fromPortalMe(result: PortalMeResult, owner: AccountOwner): AccountView {
  if (result.outcome === PortalMeOutcome.Ok) {
    return { status: 'ok', tenantId: result.tenantId, owner };
  }
  if (result.outcome === PortalMeOutcome.Aborted) {
    return { status: 'loading', owner };
  }
  if (result.outcome === PortalMeOutcome.Empty) {
    return { status: 'outage', owner };
  }
  return { status: result.outcome, owner };
}

function ownedAccount(account: AccountView, owner: AccountOwner | null): AccountView {
  if (!owner) {
    return { status: 'idle' };
  }
  if (account.status !== 'idle' && ownersMatch(account.owner, owner)) {
    return account;
  }
  return { status: 'loading', owner };
}

function PortalShell({
  fetchImpl,
  clerkLoadTimeoutMs,
  portalMeTimeoutMs,
  onRetryClerk,
}: {
  fetchImpl: typeof fetch;
  clerkLoadTimeoutMs: number;
  portalMeTimeoutMs: number;
  onRetryClerk: () => void;
}) {
  const { isLoaded, isSignedIn, userId, sessionId, getToken, signOut } = useAuth();
  const { user } = useUser();
  const navigate = useNavigate();
  const location = useLocation();
  const [clerkTimedOut, setClerkTimedOut] = useState(false);
  const [account, setAccount] = useState<AccountView>({ status: 'idle' });
  const [logout, setLogout] = useState<LogoutView>('idle');
  const [fetchEpoch, setFetchEpoch] = useState(0);
  const epochRef = useRef(0);
  const ownerRef = useRef<AccountOwner | null>(null);
  const logoutRef = useRef<LogoutView>('idle');
  const getTokenRef = useRef(getToken);

  const activeOwner = isSignedIn ? readOwner(userId, sessionId) : null;
  if (activeOwner && account.status !== 'idle' && !ownersMatch(account.owner, activeOwner)) {
    setAccount({ status: 'loading', owner: activeOwner });
  } else if (!isSignedIn && account.status !== 'idle') {
    setAccount({ status: 'idle' });
  }
  const displayAccount = ownedAccount(account, activeOwner);

  epochRef.current = fetchEpoch;
  ownerRef.current = activeOwner;
  logoutRef.current = logout;
  getTokenRef.current = getToken;

  useEffect(() => {
    if (isLoaded) {
      setClerkTimedOut(false);
      return;
    }
    const timer = window.setTimeout(() => setClerkTimedOut(true), clerkLoadTimeoutMs);
    return () => window.clearTimeout(timer);
  }, [isLoaded, clerkLoadTimeoutMs]);

  useEffect(() => {
    const onStorage = () => {
      setFetchEpoch((value) => value + 1);
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  useEffect(() => {
    if (!isLoaded || !isSignedIn || logout !== 'idle' || !activeOwner) {
      return;
    }
    if (user && !isEmailVerified(user)) {
      setAccount({ status: 'email_unverified', owner: activeOwner });
      return;
    }
    const epoch = fetchEpoch;
    const owner = activeOwner;
    const controller = new AbortController();
    setAccount({ status: 'loading', owner });
    void fetchPortalMe({
      getToken: () => getTokenRef.current(),
      fetchImpl,
      signal: controller.signal,
      timeoutMs: portalMeTimeoutMs,
    })
      .then((result) => {
        if (epoch !== epochRef.current) {
          return;
        }
        if (!ownersMatch(owner, ownerRef.current)) {
          return;
        }
        if (logoutRef.current !== 'idle') {
          return;
        }
        if (result.outcome === PortalMeOutcome.Aborted) {
          return;
        }
        setAccount(fromPortalMe(result, owner));
      })
      .catch(() => {
        if (epoch !== epochRef.current) {
          return;
        }
        if (!ownersMatch(owner, ownerRef.current)) {
          return;
        }
        if (logoutRef.current !== 'idle') {
          return;
        }
        setAccount({ status: 'outage', owner });
      });
    return () => controller.abort();
  }, [fetchEpoch, fetchImpl, isLoaded, isSignedIn, logout, portalMeTimeoutMs, sessionId, user, userId]);

  const handleSignOut = useCallback(async () => {
    setAccount({ status: 'idle' });
    setLogout('loading');
    setFetchEpoch((value) => value + 1);
    try {
      await signOut({ redirectUrl: '/' });
      setLogout('idle');
      navigate('/');
    } catch {
      setLogout('error');
    }
  }, [navigate, signOut]);

  const handleRetryFetch = useCallback(() => {
    setFetchEpoch((value) => value + 1);
  }, []);

  const userMenu = <UserButton />;
  const path = location.pathname;

  if (clerkTimedOut && !isLoaded) {
    return <OutageScreen kind="clerk" onRetry={onRetryClerk} />;
  }
  if (!isLoaded) {
    return <SignedOutScreen ready={false} onSignIn={() => undefined} onSignUp={() => undefined} />;
  }
  if (logout === 'error') {
    return <LogoutScreen mode="error" onRetry={() => void handleSignOut()} />;
  }
  if (logout === 'loading') {
    return <LogoutScreen mode="loading" />;
  }
  if (!isSignedIn) {
    if (path.startsWith('/sign-in')) {
      return (
        <SignInScreen>
          <SignIn routing="path" path="/sign-in" forceRedirectUrl="/" fallbackRedirectUrl="/" signUpUrl="/sign-up" />
        </SignInScreen>
      );
    }
    if (path.startsWith('/sign-up')) {
      return (
        <SignUpScreen>
          <SignUp routing="path" path="/sign-up" forceRedirectUrl="/" fallbackRedirectUrl="/" signInUrl="/sign-in" />
        </SignUpScreen>
      );
    }
    return <SignedOutScreen ready onSignIn={() => navigate('/sign-in')} onSignUp={() => navigate('/sign-up')} />;
  }
  if (path.startsWith('/sign-in') || path.startsWith('/sign-up')) {
    return <Navigate to="/" replace />;
  }
  if (displayAccount.status === 'email_unverified') {
    return <NotAdmittedScreen reason="email_unverified" userMenu={userMenu} onSignOut={() => void handleSignOut()} />;
  }
  if (displayAccount.status === 'not_admitted') {
    return <NotAdmittedScreen reason="not_admitted" userMenu={userMenu} onSignOut={() => void handleSignOut()} />;
  }
  if (displayAccount.status === 'outage') {
    return (
      <OutageScreen
        kind="backend"
        onRetry={handleRetryFetch}
        userMenu={userMenu}
        onSignOut={() => void handleSignOut()}
      />
    );
  }
  if (displayAccount.status === 'unauthorized') {
    return (
      <AccountScreen
        personName={personName(user)}
        tenantId={null}
        mode="error"
        userMenu={userMenu}
        onSignOut={() => void handleSignOut()}
        onRetry={handleRetryFetch}
      />
    );
  }
  return (
    <AccountScreen
      personName={personName(user)}
      tenantId={displayAccount.status === 'ok' ? displayAccount.tenantId : null}
      mode={displayAccount.status === 'ok' ? 'default' : displayAccount.status === 'empty' ? 'empty' : 'loading'}
      userMenu={userMenu}
      onSignOut={() => void handleSignOut()}
    />
  );
}

export function App({
  config = readPortalConfig(),
  fetchImpl = fetch,
  clerkLoadTimeoutMs = CLERK_LOAD_TIMEOUT_MS,
  portalMeTimeoutMs = 8_000,
}: AppProps = {}) {
  const navigate = useNavigate();
  const [providerEpoch, setProviderEpoch] = useState(0);

  if (!config.portalEnabled) {
    return <UnavailableScreen mode="degraded" />;
  }
  if (!config.publishableKey) {
    return <UnavailableScreen mode="error" />;
  }

  return (
    <ClerkProvider
      key={providerEpoch}
      publishableKey={config.publishableKey}
      afterSignOutUrl="/"
      signInUrl="/sign-in"
      signUpUrl="/sign-up"
      signInForceRedirectUrl="/"
      signUpForceRedirectUrl="/"
      signInFallbackRedirectUrl="/"
      signUpFallbackRedirectUrl="/"
      allowedRedirectOrigins={['https://app.altcontext.com']}
      telemetry={false}
      routerPush={(to) => navigate(to)}
      routerReplace={(to) => navigate(to, { replace: true })}
    >
      <Routes>
        <Route
          path="*"
          element={
            <PortalShell
              fetchImpl={fetchImpl}
              clerkLoadTimeoutMs={clerkLoadTimeoutMs}
              portalMeTimeoutMs={portalMeTimeoutMs}
              onRetryClerk={() => setProviderEpoch((value) => value + 1)}
            />
          }
        />
      </Routes>
    </ClerkProvider>
  );
}
