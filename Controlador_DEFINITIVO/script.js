// Función para añadir una nueva caja de Clase QoS
function addClass() {
    const container = document.getElementById('classesContainer');
    const div = document.createElement('div');
    div.className = 'qos-class';
    div.innerHTML = `
        <div class="qos-header">
            <h3 class="class-title">Clase de QoS</h3>
            <button type="button" class="btn-remove" onclick="removeClass(this)">🗑️ Eliminar</button>
        </div>
        <label>Burst (Bytes):</label>
        <input type="number" name="burst" value="1500" required>
        <label>CIR (Mbps):</label>
        <input type="number" name="cir" placeholder="Ej: 50" required>
        <label>Delay máximo (ms):</label>
        <input type="number" name="delay" placeholder="Ej: 10" required>
    `;
    container.appendChild(div);
    renombrarClasesVisualmente();
}

// Función para eliminar una caja de Clase QoS
function removeClass(btnElement) {
    const container = document.getElementById('classesContainer');
    if (container.children.length > 1) {
        btnElement.closest('.qos-class').remove();
        renombrarClasesVisualmente(); 
    } else {
        alert("No puedes eliminar esta clase. La Slice debe tener al menos una.");
    }
}

// Actualiza los títulos de las clases
function renombrarClasesVisualmente() {
    const clases = document.querySelectorAll('.qos-class');
    clases.forEach((div, index) => {
        div.querySelector('.class-title').innerText = 'Clase 5qc' + (index + 1);
    });
}

renombrarClasesVisualmente();

// Procesar y enviar la petición al backend
async function submitSlice(event) {
    if (event) { event.preventDefault(); }

    const delayInputs = document.querySelectorAll('input[name="delay"]');
    const tiposSeleccionados = Array.from(delayInputs).map(input => {
        const d = parseFloat(input.value);
        if (d <= 5) return "URLLC";
        if (d <= 20) return "VIDEO";
        if (d <= 50) return "TELEMETRIA";
        return "EMBB";
    });

    const tiposUnicos = new Set(tiposSeleccionados);
    
    // Validación de integridad
    if (tiposSeleccionados.length !== tiposUnicos.size) {
        alert("Error de Diseño HCTNS: No puedes asignar dos flujos con la misma categoría de latencia dentro de la misma Slice. Esto rompería el aislamiento.");
        return;
    }

    const resultBox = document.getElementById('result');
    resultBox.style.display = 'block';
    resultBox.className = '';
    resultBox.innerHTML = "⏳ Evaluando Control de Admisión...";

    const payload = {
        "network_slice": {
            "id": "auto", 
            "5G_qos_classes": {}
        }
    };

    const clasesDOM = document.querySelectorAll('.qos-class');
    let counter = 1;
    clasesDOM.forEach((div) => {
        const burst = div.querySelector('input[name="burst"]').value;
        const cir = div.querySelector('input[name="cir"]').value;
        const delay = div.querySelector('input[name="delay"]').value;

        if (cir && delay) {
            payload.network_slice["5G_qos_classes"][`5qc${counter}`] = {
                "burst": parseInt(burst),
                "cir": parseInt(cir),
                "delay": parseInt(delay)
            };
            counter++;
        }
    });

    try {
        const response = await fetch('/provision_slice', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        const data = await response.json();

        if (response.ok) {
            resultBox.className = 'success';
            resultBox.innerHTML = `✅ ¡Aceptado! Slice (VLAN ${data.slice_id}) creada.<br>Ruta asignada: ${data.ruta_elegida.join(' ➔ ')}`;
            
            const activeContainer = document.getElementById('activeSlicesContainer');
            if (activeContainer) {
                const sliceDiv = document.createElement('div');
                sliceDiv.className = 'active-slice qos-class';
                sliceDiv.innerHTML = `
                    <div class="qos-header">
                        <h3 class="class-title">VLAN ${data.slice_id}</h3>
                        <button type="button" class="btn-remove" onclick='deleteSlice(this, "${data.slice_id}")'>🗑️ Eliminar</button>
                    </div>
                    <p><strong>Ruta SRv6:</strong> ${data.ruta_elegida.join(' ➔ ')}</p>
                `;
                activeContainer.appendChild(sliceDiv);
            }
        } else {
            resultBox.className = 'error';
            resultBox.innerHTML = `❌ Rechazado: ${data.detail || 'Falta de recursos en la red.'}`;
        }
    } catch (err) {
        resultBox.className = 'error';
        resultBox.innerHTML = `❌ Error de comunicación con el Controlador SDN.`;
    }
}

async function deleteSlice(btnElement, sliceId) {
    const btnOriginalText = btnElement.innerText;
    btnElement.innerText = "⏳ Liberando...";
    btnElement.disabled = true;

    try {
        const response = await fetch(`/delete_slice/${sliceId}`, {
            method: 'DELETE'
        });

        if (response.ok) {
            alert(`✅ Recursos físicos (+20% overhead) de la VLAN ${sliceId} liberados con éxito.`);
            btnElement.closest('.active-slice').remove();
        } else {
            alert("❌ Error al liberar recursos.");
            btnElement.innerText = btnOriginalText;
            btnElement.disabled = false;
        }
    } catch (err) {
        alert("❌ Error de comunicación.");
        btnElement.innerText = btnOriginalText;
        btnElement.disabled = false;
    }
}