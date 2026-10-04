import { ClerkProvider, SignIn, SignUp, UserButton, useAuth, useUser } from '@clerk/react';
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { createPortalBillingClient } from './api/portalBilling';
import { createPortalClaimClient } from './api/portalClaim';
import { createPortalKeyClient } from './api/portalKeys';
import { fetchPortalMe, PortalMeOutcome, type PortalMeResult } from './api/portalMe';
import { createPortalRequest } from './api/portalRequest';
import { createPortalUsageClient } from './api/portalUsage';
import { WordPressTestConnectionGuidance } from './components/WordPressTestConnectionGuidance';
import { readPortalConfig, type PortalRuntimeConfig } from './config';
import { AccountScreen } from './screens/AccountScreen';
import { BillingReturnScreen } from './screens/BillingReturnScreen';
import { BillingScreen } from './screens/BillingScreen';
import { ClaimScreen } from './screens/ClaimScreen';
import { KeysScreen } from './screens/KeysScreen';
import { LogoutScreen } from './screens/LogoutScreen';
import { NotAdmittedScreen } from './screens/NotAdmittedScreen';
import { OutageScreen } from './screens/OutageScreen';
import { SignInScreen } from './screens/SignInScreen';
import { SignUpScreen } from './screens/SignUpScreen';
import { SignedOutScreen } from './screens/SignedOutScreen';
import { UnavailableScreen } from './screens/UnavailableScreen';
import { UsageScreen } from './screens/UsageScreen';

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
const PORTAL_UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const BILLING_RETURN_ATTEMPT_STORAGE_PREFIX = 'app-portal:billing-return-attempt:';

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

function readAttemptId(value: string | null | undefined): string | null {
  if (typeof value !== 'string' || !PORTAL_UUID_RE.test(value)) {
    return null;
  }
  return value;
}

function billingReturnAttemptStorageKey(tenantId: string): string {
  return `${BILLING_RETURN_ATTEMPT_STORAGE_PREFIX}${tenantId}`;
}

function storeBillingReturnAttemptId(tenantId: string, value: string | null | undefined): string | null {
  const key = billingReturnAttemptStorageKey(tenantId);
  const attemptId = readAttemptId(value);
  try {
    if (attemptId) {
      window.sessionStorage.setItem(key, attemptId);
    } else {
      window.sessionStorage.removeItem(key);
    }
  } catch {
    // Keep the in-memory route recovery available if browser storage is unavailable.
  }
  return attemptId;
}

function readStoredBillingReturnAttemptId(tenantId: string): string | null {
  const key = billingReturnAttemptStorageKey(tenantId);
  try {
    const storedAttemptId = window.sessionStorage.getItem(key);
    return readAttemptId(storedAttemptId);
  } catch {
    return null;
  }
}

function clearStoredBillingReturnAttemptIds(): void {
  try {
    const storage = window.sessionStorage;
    const keys: string[] = [];
    for (let index = 0; index < storage.length; index += 1) {
      const key = storage.key(index);
      if (key?.startsWith(BILLING_RETURN_ATTEMPT_STORAGE_PREFIX)) {
        keys.push(key);
      }
    }
    for (const key of keys) {
      storage.removeItem(key);
    }
  } catch {
    // Storage cleanup should not prevent sign-out or routing.
  }
}

function matchesPortalSegment(path: string, route: string): boolean {
  return path === route || path.startsWith(`${route}/`);
}

function matchesExactPortalPath(path: string, route: string): boolean {
  return path === route || path === `${route}/`;
}

function paymentsFromConfig(config: PortalRuntimeConfig): { paymentsEnabled: boolean; publicPlanCode: string | null } {
  const plan = typeof config.publicPlanCode === 'string' ? config.publicPlanCode.trim() : '';
  return {
    paymentsEnabled: config.paymentsEnabled === true,
    publicPlanCode: plan.length > 0 ? plan : null,
  };
}

function SessionEscape({
  userMenu,
  onSignOut,
  inert = false,
}: {
  userMenu: ReactNode;
  onSignOut: () => void;
  inert?: boolean;
}) {
  return (
    <div className="acx-session-bar" inert={inert || undefined}>
      {userMenu}
      <button type="button" className="acx-btn" onClick={onSignOut}>
        Sign out
      </button>
    </div>
  );
}

function PortalShell({
  fetchImpl,
  clerkLoadTimeoutMs,
  portalMeTimeoutMs,
  paymentsEnabled,
  publicPlanCode,
  onRetryClerk,
}: {
  fetchImpl: typeof fetch;
  clerkLoadTimeoutMs: number;
  portalMeTimeoutMs: number;
  paymentsEnabled: boolean;
  publicPlanCode: string | null;
  onRetryClerk: () => void;
}) {
  const { isLoaded, isSignedIn, userId, sessionId, getToken, signOut } = useAuth();
  const { user } = useUser();
  const navigate = useNavigate();
  const location = useLocation();
  const privateShellRef = useRef<HTMLDivElement>(null);
  const restoreKeysFocusRef = useRef(false);

  useEffect(() => {
    // Clerk owns the sign-in/up callback URLs; leave their verification data intact.
    const portalRoute =
      matchesExactPortalPath(location.pathname, '/') ||
      ['/keys', '/usage', '/billing', '/claim'].some((route) => matchesPortalSegment(location.pathname, route));
    if (portalRoute && (location.search || location.hash)) {
      navigate({ pathname: location.pathname, search: '', hash: '' }, { replace: true });
    }
  }, [location.hash, location.pathname, location.search, navigate]);

  const [clerkTimedOut, setClerkTimedOut] = useState(false);
  const [account, setAccount] = useState<AccountView>({ status: 'idle' });
  const [logout, setLogout] = useState<LogoutView>('idle');
  const [fetchEpoch, setFetchEpoch] = useState(0);
  const [returnAttemptId, setReturnAttemptId] = useState<string | null>(null);
  const epochRef = useRef(0);
  const ownerRef = useRef<AccountOwner | null>(null);
  const logoutRef = useRef<LogoutView>('idle');
  const getTokenRef = useRef(getToken);

  const activeOwner = isSignedIn ? readOwner(userId, sessionId) : null;
  if (activeOwner && account.status !== 'idle' && !ownersMatch(account.owner, activeOwner)) {
    setAccount({ status: 'loading', owner: activeOwner });
    setReturnAttemptId(null);
  } else if (!isSignedIn && account.status !== 'idle') {
    setAccount({ status: 'idle' });
    setReturnAttemptId(null);
  }
  const displayAccount = ownedAccount(account, activeOwner);

  useEffect(() => {
    if (!restoreKeysFocusRef.current || !matchesExactPortalPath(location.pathname, '/keys')) {
      return;
    }
    // The keys screen is remounted, and its guidance trigger may no longer exist.
    const heading = privateShellRef.current?.querySelector<HTMLHeadingElement>('h1');
    if (heading) {
      heading.tabIndex = -1;
      heading.focus();
      restoreKeysFocusRef.current = false;
    }
  }, [location.pathname, displayAccount.status]);

  epochRef.current = fetchEpoch;
  ownerRef.current = activeOwner;
  logoutRef.current = logout;
  getTokenRef.current = getToken;

  const ownerUserId = activeOwner?.userId ?? '';
  const ownerSessionId = activeOwner?.sessionId ?? '';
  const request = useMemo(() => {
    if (!ownerUserId) {
      return null;
    }
    const captured = { userId: ownerUserId, sessionId: ownerSessionId };
    return createPortalRequest({
      getToken: () => getTokenRef.current(),
      fetchImpl,
      timeoutMs: portalMeTimeoutMs,
      owner: captured,
      currentOwner: () => ownerRef.current,
    });
  }, [fetchImpl, ownerSessionId, ownerUserId, portalMeTimeoutMs]);

  const keyClient = useMemo(() => (request ? createPortalKeyClient(request) : null), [request]);
  const usageClient = useMemo(() => (request ? createPortalUsageClient(request) : null), [request]);
  const claimClient = useMemo(() => (request ? createPortalClaimClient(request) : null), [request]);
  const billingClient = useMemo(() => (request ? createPortalBillingClient(request) : null), [request]);

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
    if (isLoaded && !isSignedIn) {
      clearStoredBillingReturnAttemptIds();
    }
  }, [isLoaded, isSignedIn]);

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
    clearStoredBillingReturnAttemptIds();
    setReturnAttemptId(null);
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

  const handleClaimed = useCallback(() => {
    if (!ownersMatch(activeOwner, ownerRef.current)) {
      return;
    }
    if (logoutRef.current !== 'idle') {
      return;
    }
    setFetchEpoch((value) => value + 1);
  }, [activeOwner]);

  const signOutNow = () => void handleSignOut();
  const userMenu = <UserButton />;
  const path = location.pathname;
  const dismissWordPressGuidance = () => {
    restoreKeysFocusRef.current = true;
    navigate('/keys');
  };
  const wrapPrivate = (node: ReactNode) => (
    <div ref={privateShellRef} className="acx-private-shell">
      <SessionEscape
        userMenu={userMenu}
        onSignOut={signOutNow}
        inert={matchesPortalSegment(path, '/keys/wordpress')}
      />
      {node}
    </div>
  );

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
    return <NotAdmittedScreen reason="email_unverified" userMenu={userMenu} onSignOut={signOutNow} />;
  }
  if (displayAccount.status === 'not_admitted') {
    if (matchesPortalSegment(path, '/claim') && claimClient) {
      return wrapPrivate(
        <ClaimScreen
          key={`${displayAccount.owner.userId}:${displayAccount.owner.sessionId}`}
          client={claimClient}
          onClaimed={handleClaimed}
        />,
      );
    }
    return (
      <NotAdmittedScreen
        reason="not_admitted"
        userMenu={userMenu}
        onSignOut={signOutNow}
        onClaimAccess={() => navigate('/claim')}
      />
    );
  }
  if (displayAccount.status === 'outage') {
    return <OutageScreen kind="backend" onRetry={handleRetryFetch} userMenu={userMenu} onSignOut={signOutNow} />;
  }
  if (displayAccount.status === 'unauthorized') {
    return (
      <AccountScreen
        personName={personName(user)}
        tenantId={null}
        mode="error"
        userMenu={userMenu}
        onSignOut={signOutNow}
        onRetry={handleRetryFetch}
      />
    );
  }
  if (displayAccount.status !== 'ok') {
    return (
      <AccountScreen
        personName={personName(user)}
        tenantId={null}
        mode={displayAccount.status === 'empty' ? 'empty' : 'loading'}
        userMenu={userMenu}
        onSignOut={signOutNow}
      />
    );
  }

  const featureKey = `${displayAccount.owner.userId}:${displayAccount.owner.sessionId}:${displayAccount.tenantId}`;
  if (matchesPortalSegment(path, '/claim')) {
    return <Navigate to="/" replace />;
  }
  if (matchesPortalSegment(path, '/keys/wordpress')) {
    return wrapPrivate(
      <WordPressTestConnectionGuidance onClose={dismissWordPressGuidance} onReturnToKeys={dismissWordPressGuidance} />,
    );
  }
  if (matchesPortalSegment(path, '/keys') && keyClient) {
    return wrapPrivate(
      <KeysScreen
        client={keyClient}
        sessionKey={featureKey}
        onNavigateToUsage={() => navigate('/usage')}
        onNavigateToBilling={() => navigate('/billing')}
        onOpenWordPressGuidance={() => navigate('/keys/wordpress')}
      />,
    );
  }
  if (matchesPortalSegment(path, '/usage') && usageClient) {
    return wrapPrivate(
      <UsageScreen
        client={usageClient}
        sessionKey={featureKey}
        onNavigateToKeys={() => navigate('/keys')}
        onNavigateToBilling={() => navigate('/billing')}
      />,
    );
  }
  if (matchesPortalSegment(path, '/billing/return') && billingClient) {
    return wrapPrivate(
      <BillingReturnScreen
        client={billingClient}
        publicPlanCode={publicPlanCode}
        paymentsEnabled={paymentsEnabled}
        attemptId={returnAttemptId ?? readStoredBillingReturnAttemptId(displayAccount.tenantId)}
        onNavigateToBilling={() => navigate('/billing')}
        onNavigateToUsage={() => navigate('/usage')}
      />,
    );
  }
  if (matchesExactPortalPath(path, '/billing/cancel') && billingClient) {
    return wrapPrivate(
      <BillingScreen
        client={billingClient}
        publicPlanCode={publicPlanCode}
        paymentsEnabled={paymentsEnabled}
        cancellationNotice={{ onRetry: () => navigate('/billing') }}
        onNavigateToReturn={(attemptId) => {
          setReturnAttemptId(storeBillingReturnAttemptId(displayAccount.tenantId, attemptId));
          navigate('/billing/return');
        }}
        onNavigateToUsage={() => navigate('/usage')}
      />,
    );
  }
  if (matchesExactPortalPath(path, '/billing') && billingClient) {
    return wrapPrivate(
      <BillingScreen
        client={billingClient}
        publicPlanCode={publicPlanCode}
        paymentsEnabled={paymentsEnabled}
        onNavigateToReturn={(attemptId) => {
          setReturnAttemptId(storeBillingReturnAttemptId(displayAccount.tenantId, attemptId));
          navigate('/billing/return');
        }}
        onNavigateToUsage={() => navigate('/usage')}
      />,
    );
  }
  return (
    <AccountScreen
      personName={personName(user)}
      tenantId={displayAccount.tenantId}
      mode="default"
      userMenu={userMenu}
      onSignOut={signOutNow}
      onNavigateToKeys={() => navigate('/keys')}
      onNavigateToUsage={() => navigate('/usage')}
      onNavigateToBilling={() => navigate('/billing')}
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
  const payments = paymentsFromConfig(config);

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
              paymentsEnabled={payments.paymentsEnabled}
              publicPlanCode={payments.publicPlanCode}
              onRetryClerk={() => setProviderEpoch((value) => value + 1)}
            />
          }
        />
      </Routes>
    </ClerkProvider>
  );
}
