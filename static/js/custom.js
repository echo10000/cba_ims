/**
 * CBA IMS - Custom JavaScript
 * Handles mobile interactions, auto-dismiss alerts, confirmations
 */
document.addEventListener('DOMContentLoaded', function() {

    // === Auto-dismiss alerts after 5 seconds ===
    document.querySelectorAll('.alert-dismissible').forEach(function(alert) {
        setTimeout(function() {
            var bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
            if (bsAlert) bsAlert.close();
        }, 5000);
    });

    // === Confirm action dialogs ===
    document.querySelectorAll('.confirm-action').forEach(function(el) {
        el.addEventListener('click', function(e) {
            var msg = this.getAttribute('data-confirm') || 'Are you sure you want to perform this action?';
            if (!confirm(msg)) {
                e.preventDefault();
                e.stopPropagation();
            }
        });
    });

    // === Confirm form submission ===
    document.querySelectorAll('form[data-confirm]').forEach(function(form) {
        form.addEventListener('submit', function(e) {
            if (!confirm(this.getAttribute('data-confirm'))) {
                e.preventDefault();
            }
        });
    });

    // === Mobile filter toggle ===
    document.querySelectorAll('.filter-collapse-btn').forEach(function(btn) {
        btn.addEventListener('click', function() {
            var target = document.querySelector(this.getAttribute('data-target'));
            if (target) {
                target.classList.toggle('show');
                this.querySelector('i').classList.toggle('bi-funnel');
                this.querySelector('i').classList.toggle('bi-funnel-fill');
            }
        });
    });

    // === Close offcanvas on nav link click (for same-page anchors) ===
    var offcanvasEl = document.getElementById('mobileSidebar');
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
