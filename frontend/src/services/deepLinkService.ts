import { App as CapApp, URLOpenListenerEvent } from '@capacitor/app';
import { isNativePlatform } from './platformService';

/**
 * Extracts a signed attendance QR token from either:
 * - https://<domain>/attend/verify?token=...
 * - smartpresence://attend/verify?token=...
 */
export function extractTokenFromUrl(urlString: string): string | null {
  try {
    const parsed = new URL(urlString);
    const token = parsed.searchParams.get('token');
    return token ? token.trim() : null;
  } catch {
    return null;
  }
}

/**
 * Registers a native Capacitor deep-link listener (Android App Links / iOS Universal Links / custom scheme).
 * Returns a cleanup function.
 */
export function registerDeepLinkListener(onTokenReceived: (token: string) => void): () => void {
  if (!isNativePlatform()) {
    return () => {};
  }

  let removeHandle: (() => Promise<void>) | null = null;

  CapApp.addListener('appUrlOpen', (event: URLOpenListenerEvent) => {
    const token = extractTokenFromUrl(event.url);
    if (token) {
      console.info('[DeepLink] Captured attendance token from native URL');
      sessionStorage.setItem('sp_pending_qr_token', token);
      onTokenReceived(token);
    }
  })
    .then((handle) => {
      removeHandle = () => handle.remove();
    })
    .catch((err) => {
      console.warn('[DeepLink] Failed to attach appUrlOpen listener:', err);
    });

  // Also check if app was cold-launched with a URL
  CapApp.getLaunchUrl()
    .then((launch) => {
      if (launch?.url) {
        const token = extractTokenFromUrl(launch.url);
        if (token) {
          sessionStorage.setItem('sp_pending_qr_token', token);
          onTokenReceived(token);
        }
      }
    })
    .catch(() => {});

  return () => {
    if (removeHandle) {
      void removeHandle();
    }
  };
}
