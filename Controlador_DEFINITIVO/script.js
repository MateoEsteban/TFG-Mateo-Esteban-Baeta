// Función para añadir una nueva caja de Clase QoS
function addClass() {
    const container = document.getElementById('classesContainer');
    const div = document.createElement('div');
    div.className = 'qos-class';
    div.innerHTML = `
        <div class="qos-header">
            <h3 class="class-title">Clase de QoS</h3>
            <button type="button" class="btn-remove" onclick="removeClass(this)">🗑 Eliminar</button>
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

// Actualiza los títulos "Clase 1, Clase 2" para que siempre tengan sentido aunque borres las del medio
function renombrarClasesVisualmente() {
    const clases = document.querySelectorAll('.qos-class');
    clases.forEach((div, index) => {
        div.querySelector('.class-title').innerText = 'Clase 5qc' + (index + 1);
    });
}

// Llamar a la función al arrancar para inicializar el título de la primera caja
renombrarClasesVisualmente();

// Función para procesar y enviar la petición al backend
// Función para procesar y enviar la petición al backend
async function submitSlice(event) {
    // Bloqueamos el recargo automático de la página web al pulsar el botón
    if (event) {
        event.preventDefault();
    }

    const delayInputs = document.querySelectorAll('input[name="delay"]');
    
    // Mapear los valores de delay a su clase (TNA, TNB, TNC, TND)
    const tiposSeleccionados = Array.from(delayInputs).map(input => {
        const d = parseFloat(input.value);
        if (d <= 5) return "URLLC";
        if (d <= 20) return "VIDEO";
        if (d <= 50) return "TELEMETRIA";
        return "EMBB";
    });

    const tiposUnicos = new Set(tiposSeleccionados);

    // Validación de integridad del modelo HCTNS
    if (tiposSeleccionados.length !== tiposUnicos.size) {
        alert("Error de Diseño HCTNS: No puedes asignar dos flujos con la misma categoría de latencia dentro de la misma Slice. Esto rompería el aislamiento en el router frontera.");
        return;
    }

    const resultBox = document.getElementById('result');
    resultBox.style.display = 'block';
    resultBox.className = '';
    resultBox.innerHTML = "⏳ Evaluando Control de Admisión...";

    // Construir el JSON exacto que espera FastAPI (Dejamos que el Backend asigne la VLAN)
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
        // Enviar la petición POST al backend
        const response = await fetch('/provision_slice', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        });

        const data = await response.json();

        // Mostrar si se acepta o rechaza, leyendo la VLAN directamente del controlador SDN
        if (response.ok) {
            resultBox.className = 'success';
            resultBox.innerHTML = `✅ ¡Aceptado! Slice (VLAN ${data.slice_id}) creada.<br>Ruta asignada: ${data.ruta_elegida.join(' ➔ ')}`;

            // Localizamos el contenedor vacío en el HTML
            const activeSlicesContainer = document.getElementById('slicesActivasContainer');
            
            if (activeSlicesContainer) {
                // Creamos un nuevo Div para la Slice
                const nuevaSlice = document.createElement('div');
                nuevaSlice.className = 'slice-card'; 
                
                // Dibujamos el HTML interno inyectando la variable dinámica ${data.slice_id}
                nuevaSlice.innerHTML = `
                    <h4>🌐 Slice VLAN ${data.slice_id}</h4>
                    <p><strong>Ruta asignada:</strong> ${data.ruta_elegida.join(' ➔ ')}</p>
                    <button class="btn-remove-slice" onclick="eliminarSliceWeb('${data.slice_id}', this)">🗑️ Eliminar</button>
                `;
                
                // Lo añadimos a la pantalla
                activeSlicesContainer.appendChild(nuevaSlice);
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

// Función para eliminar una Slice Activa y liberar recursos en los routers físicos
async function eliminarSliceWeb(slice_id, btnElement) {
    if (!confirm(`¿Estás seguro de que quieres eliminar la Slice VLAN ${slice_id} y destruir sus colas?`)) {
        return;
    }

    try {
        const response = await fetch(`/delete_slice/${slice_id}`, {
            method: 'DELETE'
        });

        if (response.ok) {
            // Borra la caja visual de la web (adaptado a tu clase css 'slice-card' o 'qos-class')
            btnElement.closest('div').remove(); 
            alert(`✅ Slice ${slice_id} eliminada. Colas destruidas y recursos físicos liberados.`);
        } else {
            const errorData = await response.json();
            alert(`❌ Error al eliminar: ${errorData.detail}`);
        }
    } catch (err) {
        alert("❌ Error de comunicación con el Controlador SDN.");
    }
}