/**
 * CBA IMS - Custom JavaScript
 * Handles mobile interactions, auto-dismiss alerts, confirmations,
 * HTMX CSRF integration, and PWA service worker registration.
 */

// === Helper to retrieve cookie by name ===
function getCookie(name) {
    var cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        var cookies = document.cookie.split(';');
        for (var i = 0; i < cookies.length; i++) {
            var cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

// === HTMX CSRF Token Configuration ===
// Ensures all future HTMX AJAX requests include the Django CSRF token
document.addEventListener('htmx:configRequest', function(evt) {
    if (!evt.detail.headers['X-CSRFToken']) {
        var csrfToken = getCookie('csrftoken') ||
            (document.querySelector('meta[name="csrf-token"]') ? document.querySelector('meta[name="csrf-token"]').getAttribute('content') : null) ||
            (document.querySelector('[name=csrfmiddlewaretoken]') ? document.querySelector('[name=csrfmiddlewaretoken]').value : null);
        if (csrfToken) {
            evt.detail.headers['X-CSRFToken'] = csrfToken;
        }
    }
});

// === PWA Service Worker Registration ===
if ('serviceWorker' in navigator) {
    window.addEventListener('load', function() {
        navigator.serviceWorker.register('/static/sw.js').catch(function(err) {
            console.warn('[SW] Registration failed:', err);
        });
    });
}

document.addEventListener('DOMContentLoaded', function() {

    // === Auto-dismiss alerts after 5 seconds ===
    document.querySelectorAll('.alert-dismissible').forEach(function(alert) {
        setTimeout(function() {
            var bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
            if (bsAlert) bsAlert.close();
        }, 5000);
    });

    // === Confirm action dialogs (retained for non-migrated complex workflows) ===
    document.querySelectorAll('.confirm-action').forEach(function(el) {
        el.addEventListener('click', function(e) {
            var msg = this.getAttribute('data-confirm') || 'Are you sure you want to perform this action?';
            if (!confirm(msg)) {
                e.preventDefault();
                e.stopPropagation();
            }
        });
    });

    // === Confirm form submission (retained for non-migrated complex workflows) ===
    document.querySelectorAll('form[data-confirm]').forEach(function(form) {
        form.addEventListener('submit', function(e) {
            if (!confirm(this.getAttribute('data-confirm'))) {
                e.preventDefault();
            }
        });
    });

    // === Close offcanvas on nav link click (for same-page anchors / mobile navigation) ===
    var offcanvasEl = document.getElementById('sidebarMenu') || document.getElementById('mobileSidebar');
    if (offcanvasEl) {
        offcanvasEl.querySelectorAll('a.nav-link').forEach(function(link) {
            link.addEventListener('click', function() {
                var offcanvas = bootstrap.Offcanvas.getInstance(offcanvasEl);
                if (offcanvas) offcanvas.hide();
            });
        });
    }

    // === Responsive table: auto-add horizontal scroll indicator ===
    document.querySelectorAll('.table-responsive').forEach(function(wrapper) {
        var table = wrapper.querySelector('table');
        if (table && table.offsetWidth > wrapper.offsetWidth) {
            wrapper.classList.add('has-scroll');
        }
    });

    // === Back to top (if element exists) ===
    var backToTop = document.getElementById('backToTop');
    if (backToTop) {
        window.addEventListener('scroll', function() {
            backToTop.style.display = window.scrollY > 300 ? 'block' : 'none';
        });
        backToTop.addEventListener('click', function() {
            window.scrollTo({ top: 0, behavior: 'smooth' });
        });
    }
});
