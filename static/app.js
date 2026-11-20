const rows = document.querySelector('#rows');
const modal = document.querySelector('#modal');
const form = document.querySelector('#form');

async function api(path, opts = {}) {
    const r = await fetch(path, {
        headers: { 'Content-Type': 'application/json' },
        ...opts
    });

    if (!r.ok) {
        let d = await r.json().catch(() => ({ detail: 'Request failed' }));
        throw Error(d.detail || 'Request failed');
    }

    return r.json();
}

function safe(s) {
    return String(s).replace(/[&<>"']/g, c => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
    }[c]));
}

function render(nodes) {
    rows.innerHTML = nodes.map(n => `
        <tr>
            <td class="node-name">◉ &nbsp;${safe(n.name)}</td>
            <td>${safe(n.region)}</td>
            <td>
                <span class="badge ${n.status}">
                    ${n.status.toUpperCase()}
                </span>
            </td>
            <td>${n.players ?? 0}</td>
            <td>${n.capacity}</td>
            <td>${n.ping == null ? '—' : n.ping + ' ms'}</td>
            <td>
                <button class="action"
                    data-action="toggle"
                    data-id="${n.id}"
                    data-status="${n.status}">
                    ${n.status === 'online' ? 'Disable' : 'Enable'}
                </button>

                <button class="action"
                    data-action="delete"
                    data-id="${n.id}">
                    Remove
                </button>
            </td>
        </tr>
    `).join('');

    document.querySelector('#total').textContent = nodes.length;

    document.querySelector('#online').textContent =
        nodes.filter(n => n.status === 'online').length;

    document.querySelector('#players').textContent =
        nodes.reduce((sum, n) => sum + (n.players || 0), 0);
}

async function refresh() {
    try {
        const d = await api('/api/servers');
        render(d.servers);
    } catch (e) {
        rows.innerHTML = `
            <tr>
                <td colspan="7">
                    Could not load nodes: ${safe(e.message)}
                </td>
            </tr>
        `;
    }
}

document.querySelector('#addOpen').onclick = () => {
    modal.classList.add('show');
};

document.querySelector('#close').onclick = () => {
    modal.classList.remove('show');
};

modal.addEventListener('click', e => {
    if (e.target === modal) {
        modal.classList.remove('show');
    }
});

form.onsubmit = async e => {
    e.preventDefault();

    const fd = new FormData(form);

    try {
        await api('/api/servers', {
            method: 'POST',
            body: JSON.stringify({
                name: fd.get('name'),
                region: fd.get('region'),
                capacity: Number(fd.get('capacity'))
            })
        });

        form.reset();
        modal.classList.remove('show');
        refresh();

    } catch (err) {
        alert(err.message);
    }
};

rows.onclick = async e => {
    const b = e.target.closest('button[data-action]');
    if (!b) return;

    try {
        if (b.dataset.action === 'delete') {
            if (!confirm('Remove this node?')) return;

            await api('/api/servers/' + b.dataset.id, {
                method: 'DELETE'
            });

        } else {
            const status = b.dataset.status === 'online'
                ? 'offline'
                : 'online';

            await api('/api/servers/' + b.dataset.id, {
                method: 'PATCH',
                body: JSON.stringify({ status })
            });
        }

        refresh();

    } catch (err) {
        alert(err.message);
    }
};

refresh();
setInterval(refresh, 15000);
