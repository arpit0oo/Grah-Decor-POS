/* ═══════════════════════════════════════════════════════════════
   Grah Decor POS — Client-side JavaScript
   ═══════════════════════════════════════════════════════════════ */

// ── Sidebar Toggle (Mobile) ─────────────────────────────────
document.addEventListener('DOMContentLoaded', function () {
    const toggle = document.getElementById('sidebarToggle');
    const sidebar = document.getElementById('sidebar');

    if (toggle && sidebar) {
        toggle.addEventListener('click', function () {
            sidebar.classList.toggle('open');
        });

        // Close sidebar when clicking outside
        document.addEventListener('click', function (e) {
            if (sidebar.classList.contains('open') &&
                !sidebar.contains(e.target) &&
                !toggle.contains(e.target)) {
                sidebar.classList.remove('open');
            }
        });
    }

    // ── Auto-dismiss flash messages ─────────────────────────
    const flashes = document.querySelectorAll('.flash');
    flashes.forEach(function (flash) {
        setTimeout(function () {
            flash.style.transition = 'opacity 0.3s, transform 0.3s';
            flash.style.opacity = '0';
            flash.style.transform = 'translateY(-8px)';
            setTimeout(function () { flash.remove(); }, 300);
        }, 4000);
    });
});


// ── Toggle form visibility ──────────────────────────────────
function toggleForm(formId) {
    var el = document.getElementById(formId);
    if (el) el.classList.toggle('hidden');
}


// ── Close modal ─────────────────────────────────────────────
function closeModal(modalId) {
    var el = document.getElementById(modalId);
    if (el) el.classList.add('hidden');
}

// Close modal on overlay click
document.addEventListener('click', function (e) {
    if (e.target.classList.contains('modal-overlay')) {
        e.target.classList.add('hidden');
    }
});

// Close modal on Escape key
document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
        document.querySelectorAll('.modal-overlay').forEach(function (m) {
            m.classList.add('hidden');
        });
    }
});
