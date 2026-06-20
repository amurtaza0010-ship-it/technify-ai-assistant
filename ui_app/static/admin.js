let jwtToken = localStorage.getItem('taia_jwt') || "";
let userRole = localStorage.getItem('taia_role') || "";

window.onload = function() {
    fetchLogs();
};

async function fetchLogs() {
    const tbody = document.getElementById('logsTableBody');
    tbody.innerHTML = '<tr><td colspan="6" style="text-align: center;">Loading logs...</td></tr>';
    
    // Build headers for authentication
    const headers = {};
    if (jwtToken) {
        headers['Authorization'] = `Bearer ${jwtToken}`;
    } else if (userRole.toLowerCase() === 'admin') {
        headers['x-user-role'] = 'Admin';
        headers['x-user-id'] = 'ADM-0001';
    } else {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: #ef4444;">Please login as an Admin in the main Chat UI first.</td></tr>`;
        return;
    }

    try {
        const apiUrl = `http://${window.location.hostname}:8000/api/v1/admin/audit-logs`;
        const response = await fetch(apiUrl, {
            method: 'GET',
            headers: headers
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.detail || 'Authentication failed. Please check your token or role.');
        }

        const logs = await response.json();
        
        // Update stats
        document.getElementById('totalQueries').textContent = logs.length;
        
        let totalLatency = 0;
        let validLatencies = 0;
        
        tbody.innerHTML = '';
        if (logs.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align: center;">No logs found.</td></tr>';
            return;
        }

        logs.forEach(log => {
            if (log.latency !== null && log.latency !== undefined) {
                totalLatency += parseFloat(log.latency);
                validLatencies++;
            }
            
            const tr = document.createElement('tr');
            
            // Format timestamp nicely
            const date = new Date(log.timestamp);
            const formattedDate = date.toLocaleString();

            tr.innerHTML = `
                <td>#${log.id}</td>
                <td style="color: #888;">${formattedDate}</td>
                <td style="font-family: monospace;">${log.user_id}</td>
                <td><span class="badge" style="background-color: ${log.role.toLowerCase() === 'admin' ? '#ef4444' : '#3b82f6'};">${log.role}</span></td>
                <td>${log.intent || '-'}</td>
                <td style="color: #10b981;">${log.latency ? log.latency + 's' : '-'}</td>
            `;
            tbody.appendChild(tr);
        });

        if (validLatencies > 0) {
            const avg = (totalLatency / validLatencies).toFixed(2);
            document.getElementById('avgLatency').textContent = avg;
        } else {
            document.getElementById('avgLatency').textContent = "-";
        }

    } catch (error) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: #ef4444;">Error fetching logs: ${error.message}</td></tr>`;
    }
}
