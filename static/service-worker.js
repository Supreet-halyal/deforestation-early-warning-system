// Deforestation Early Warning System
// Web Push Service Worker

self.addEventListener("push", function(event) {

    let data = {};

    try {
        data = event.data ? event.data.json() : {};
    } catch (error) {
        data = {
            title: "Deforestation Alert",
            body: event.data
                ? event.data.text()
                : "New alert received."
        };
    }

    const title =
        data.title || "🚨 Deforestation Alert";

    const options = {
        body:
            data.body ||
            "A new forest monitoring alert requires attention.",

        icon:
            data.icon ||
            "/static/icon-192.png",

        badge:
            data.badge ||
            "/static/icon-192.png",

        data: data.url
            ? { url: data.url }
            : {},

        requireInteraction: true
    };

    event.waitUntil(
        self.registration.showNotification(
            title,
            options
        )
    );

});


self.addEventListener(
    "notificationclick",
    function(event) {

        event.notification.close();

        const targetUrl =
            event.notification.data &&
            event.notification.data.url
                ? event.notification.data.url
                : "/officer";

        event.waitUntil(

            clients.matchAll({
                type: "window",
                includeUncontrolled: true
            }).then(function(clientList) {

                for (const client of clientList) {

                    if ("focus" in client) {
                        client.navigate(targetUrl);
                        return client.focus();
                    }

                }

                if (clients.openWindow) {
                    return clients.openWindow(targetUrl);
                }

            })

        );

    }
);  