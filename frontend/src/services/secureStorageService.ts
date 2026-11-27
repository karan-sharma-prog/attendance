import { SecureStoragePlugin } from 'capacitor-secure-storage-plugin';
import { isNativePlatform } from './platformService';

/**
 * Platform-backed secure storage service.
 * - On Android/iOS (Capacitor): Uses Android Keystore / iOS Keychain via SecureStoragePlugin.
 * - On Web: Uses localStorage so scanning a QR in a new mobile browser tab stays logged in
 *   without forcing the student to re-enter credentials every time.
 */
export async function setSecureItem(key: string, value: string): Promise<void> {
  if (isNativePlatform()) {
    try {
      await SecureStoragePlugin.set({ key, value });
      return;
    } catch (err) {
      console.warn('[SecureStorage] Native set failed, falling back to localStorage:', err);
    }
  }
  localStorage.setItem(key, value);
}

export async function getSecureItem(key: string): Promise<string | null> {
  if (isNativePlatform()) {
    try {
      const res = await SecureStoragePlugin.get({ key });
      return res.value ?? null;
    } catch {
      return null;
    }
  }
  return localStorage.getItem(key) || sessionStorage.getItem(key);
}

export async function removeSecureItem(key: string): Promise<void> {
  if (isNativePlatform()) {
    try {
      await SecureStoragePlugin.remove({ key });
      return;
    } catch {
      // Ignore missing key errors
    }
  }
  localStorage.removeItem(key);
  sessionStorage.removeItem(key);
}
