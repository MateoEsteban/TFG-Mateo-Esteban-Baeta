// Añade una nueva clase de QoS al formulario
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

// Elimina una clase de QoS del formulario
function removeClass(btnElement) {
    const container = document.getElementById('classesContainer');
    if (container.children.length > 1) {
        btnElement.closest('.qos-class').remove();
        renombrarClasesVisualmente();
    } else {
        alert("No puedes eliminar esta clase. La Slice debe tener al menos una.");
    }
}

// Actualiza los números secuenciales de las clases al añadir o eliminar
function renombrarClasesVisualmente() {
    const clases = document.querySelectorAll('.qos-class');
    clases.forEach((div, index) => {
        div.querySelector('.class-title').innerText = 'Clase 5qc' + (index + 1);
    });
}

// Inicializar los números de clases al cargar la página
renombrarClasesVisualmente();

// Procesa y envía la petición de provisión de slice al controlador
async function submitSlice(event) {
    // Prevenir recarga automática de la página
    if (event) {
        event.preventDefault();
    }

    const delayInputs = document.querySelectorAll('input[name="delay"]');
    
    // Mapear valores de latencia a categorías SLA estándar
    const tiposSeleccionados = Array.from(delayInputs).map(input => {
        const d = parseFloat(input.value);
        if (d <= 5) return "URLLC";
        if (d <= 20) return "VIDEO";
        if (d <= 50) return "TELEMETRIA";
        return "EMBB";
    });

    const tiposUnicos = new Set(tiposSeleccionados);

    // Validación de modelo HCTNS: evitar múltiples flujos con igual latencia
    if (tiposSeleccionados.length !== tiposUnicos.size) {
        alert("Error de Diseño HCTNS: No puedes asignar dos flujos con la misma categoría de latencia dentro de la misma Slice. Esto rompería el aislamiento en el router frontera.");
        return;
    }

    const resultBox = document.getElementById('result');
    resultBox.style.display = 'block';
    resultBox.className = '';
    resultBox.innerHTML = "⏳ Evaluando Control de Admisión...";

    // Construir la solicitud para el backend
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
        // Enviar solicitud al controlador SDN
        const response = await fetch('/provision_slice', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        });

        const data = await response.json();

        // Mostrar resultado basado en la respuesta del controlador
        if (response.ok) {
            resultBox.className = 'success';
            resultBox.innerHTML = `✅ ¡Aceptado! Slice (VLAN ${data.slice_id}) creada.<br>Ruta asignada: ${data.ruta_elegida.join(' ➔ ')}`;

            // Agregar tarjeta visual de la nueva slice
            const activeSlicesContainer = document.getElementById('slicesActivasContainer');
            
            if (activeSlicesContainer) {
                const nuevaSlice = document.createElement('div');
                nuevaSlice.className = 'slice-card'; 
                //Extraer datos del payload para el resumen
                const clasesQoS = payload.network_slice["5G_qos_classes"];
                const numClases = Object.keys(clasesQoS).length;
                let sumaCir = 0;
                let retardoMinimo = Infinity;

                for (const key in clasesQoS) {
                    sumaCir += clasesQoS[key].cir;
                    if (clasesQoS[key].delay < retardoMinimo) {
                        retardoMinimo = clasesQoS[key].delay;
                    }
                }

                // Inyectar información dinámica de la slice
                nuevaSlice.innerHTML = `
                    <h4>🌐 Slice VLAN ${data.slice_id}</h4>
                    <p><strong>Ruta asignada:</strong> ${data.ruta_elegida.join(' ➔ ')}</p>
                    <p><strong>Número de Clases QoS:</strong> ${numClases}</p>
                    <p><strong>Suma CIR:</strong> ${sumaCir}</p>
                    <p><strong>Retardo Mínimo:</strong> ${retardoMinimo}</p>
                    <button class="btn-remove-slice" onclick="eliminarSliceWeb('${data.slice_id}', this)">🗑️ Eliminar</button>
                `;

                // Agregar al contenedor
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

// Elimina una slice activa y libera los recursos en los routers
async function eliminarSliceWeb(slice_id, btnElement) {
    if (!confirm(`¿Estás seguro de que quieres eliminar la Slice VLAN ${slice_id} y destruir sus colas?`)) {
        return;
    }

    try {
        const response = await fetch(`/delete_slice/${slice_id}`, {
            method: 'DELETE'
        });

        if (response.ok) {
            // Remover la tarjeta visual de la slice desde el DOM
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