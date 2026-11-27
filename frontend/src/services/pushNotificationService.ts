import { PushNotifications } from '@capacitor/push-notifications';
import { isNativePlatform } from './platformService';

export interface PushInitCallbacks {
  onToken?: (deviceToken: string) => void;
  onNotificationReceived?: (title: string, body: string) => void;
}

/**
 * Registers native push notifications on Android/iOS via Capacitor PushNotifications.
 * Gracefully no-ops in web browsers.
 */
export async function initPushNotifications(callbacks: PushInitCallbacks = {}): Promise<void> {
  if (!isNativePlatform()) return;

  try {
    let perm = await PushNotifications.checkPermissions();
    if (perm.receive === 'prompt') {
      perm = await PushNotifications.requestPermissions();
    }
    if (perm.receive !== 'granted') {
      console.info('[PushNotifications] Permission not granted by user.');
      return;
    }

    await PushNotifications.addListener('registration', (token) => {
      console.info('[PushNotifications] Registered native device token.');
      if (callbacks.onToken) callbacks.onToken(token.value);
    });

    await PushNotifications.addListener('registrationError', (err) => {
      console.warn('[PushNotifications] Registration error:', err);
    });

    await PushNotifications.addListener('pushNotificationReceived', (notification) => {
      if (callbacks.onNotificationReceived) {
        callbacks.onNotificationReceived(
          notification.title || 'SmartPresence',
          notification.body || 'New attendance update'
        );
      }
    });

    await PushNotifications.register();
  } catch (err) {
    console.warn('[PushNotifications] Initialization skipped:', err);
  }
}
