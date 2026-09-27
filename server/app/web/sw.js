/*
 * Service worker кабинета.
 *
 * Единственная его работа — показать уведомление, когда кабинет
 * закрыт. Браузер держит этот файл отдельно от страницы и будит его
 * сам, поэтому здесь нельзя полагаться ни на что со страницы: ни на
 * токен, ни на настройки, ни на то, что кабинет вообще открыт.
 *
 * Кэшированием страниц намеренно не занимаемся. Запись зависит от
 * живого сервера: свободное окно надо спросить, а не показать
 * вчерашнее — иначе двое запишутся на одно время. Отдавать кабинет из
 * кэша значит врать человеку о том, что место свободно.
 */

// Сообщение приходит зашифрованным, расшифровывает его браузер.
// Внутри — то, что положил сервер: заголовок, текст, куда открыть
self.addEventListener('push', function (event) {
  var data = {};

  try {
    data = event.data ? event.data.json() : {};
  } catch (e) {
    // Если разобрать не удалось, лучше показать хоть что-то, чем
    // промолчать: человек ждёт напоминания, а не тишины
    data = { body: event.data ? event.data.text() : '' };
  }

  var title = data.title || 'Шиномонтаж';
  var options = {
    body: data.body || '',
    icon: '/z/icon.svg',
    badge: '/z/icon.svg',
    // Одна и та же запись не должна висеть в шторке двумя строками:
    // перенесли время — новое уведомление заменяет прежнее
    tag: data.tag || 'tire',
    renotify: true,
    data: { url: data.url || '/z' }
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

// Нажали на уведомление — открыть кабинет. Если он уже открыт где-то
// во вкладке, переключаемся на неё, а не заводим вторую
self.addEventListener('notificationclick', function (event) {
  event.notification.close();

  var target = (event.notification.data && event.notification.data.url) || '/z';

  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true })
      .then(function (windows) {
        for (var i = 0; i < windows.length; i++) {
          if (windows[i].url.indexOf('/z') !== -1 && 'focus' in windows[i]) {
            windows[i].navigate(target);
            return windows[i].focus();
          }
        }

        if (self.clients.openWindow) {
          return self.clients.openWindow(target);
        }
      })
  );
});

// Браузер может сам перевыдать подписку — например, после обновления.
// Старый адрес при этом перестаёт работать, и если промолчать,
// уведомления тихо прекратятся. Просим страницу подписаться заново
self.addEventListener('pushsubscriptionchange', function (event) {
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true })
      .then(function (windows) {
        windows.forEach(function (window) {
          window.postMessage({ kind: 'push-resubscribe' });
        });
      })
  );
});

// Новую версию применяем сразу, не дожидаясь, пока человек закроет все
// вкладки: показывать уведомления старым файлом незачем
self.addEventListener('install', function () {
  self.skipWaiting();
});

self.addEventListener('activate', function (event) {
  event.waitUntil(self.clients.claim());
});
