from fastapi import FastAPI, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import pce
import src
import subprocess

vlan_global_counter = 3000
active_slices = {}  # Memoria del controlador para guardar el estado

def check_containers_running(required_nodes):
    try:
        result = subprocess.run(['sudo', 'lxc-ls', '--running'], capture_output=True, text=True)
        running_containers = result.stdout.split() if result.stdout else []
        return all(node in running_containers for node in required_nodes)
    except Exception as e:
        return False

app = FastAPI(title="Controlador SDN - Orquestador de Slices")
app.mount("/static", StaticFiles(directory="."), name="static")

@app.get("/", response_class=HTMLResponse)
async def serve_webpage():
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "Error: No se encuentra index.html"

@app.post("/provision_slice")
async def provision_slice(peticion: dict):
    global vlan_global_counter
    print("\n[API] Recibida nueva petición de provisión de Slice...")
    
    topologia = ['rg', 'r1', 'r2', 'r3', 'r4', 'r5', 'r6', 'r7', 'ru']
    if not check_containers_running(topologia):
        raise HTTPException(status_code=503, detail="Infraestructura VNX no operativa.")

    slice_data = peticion.get("network_slice", {})
    qos_classes = slice_data.get("5G_qos_classes", {})
    if not qos_classes:
        raise HTTPException(status_code=400, detail="Faltan clases QoS.")

    req_cir_total = sum(cls.get("cir", 0) for cls in qos_classes.values())
    req_delay_min = min(cls.get("delay", 100) for cls in qos_classes.values())

    # LA REGLA DE AITOR: Añadimos un 20% de overhead por las cabeceras SRv6 e IPv6
    req_cir_fisico = req_cir_total * 1.2

    print(f"[API] Requisitos -> CIR Útil (HTB): {req_cir_total} Mbps | CIR Físico (Topología): {req_cir_fisico} Mbps")

    G = pce.create_graph()
    # El PCE busca hueco con los megas físicos (ej: 40 * 1.2 = 48 Mbps)
    ruta_asignada = pce.control_de_admision(G, "rg", "ru", req_cir_fisico, req_delay_min)

    if ruta_asignada:
        vlan_global_counter += 1
        vlan_asignada = str(vlan_global_counter)
        print(f"[API] ✅ Slice admitida. Se ha asignado la VLAN {vlan_asignada}")

        # El PCE descuenta los megas físicos (48 Mbps)
        pce.actualizar_networkinfo(ruta_asignada, req_cir_fisico)

        # El SRC configura la cola HTB limitando estrictamente a los megas útiles (40 Mbps)
        exito = src.inyectar_comandos_router(vlan_asignada, req_cir_total, ruta_asignada, req_delay_min, qos_classes)

        if not exito:
            raise HTTPException(status_code=500, detail="Error de sistema operativo.")

        # Guardamos en memoria para facilitar el borrado
        active_slices[vlan_asignada] = {
            "ruta": ruta_asignada,
            "cir": req_cir_total
        }

        return {"slice_id": vlan_asignada, "ruta_elegida": ruta_asignada}
    else:
        raise HTTPException(status_code=406, detail="Saturación: No hay recursos físicos suficientes.")


@app.delete("/delete_slice/{slice_id}")
async def delete_slice(slice_id: str):
    global active_slices
    
    if slice_id not in active_slices:
        raise HTTPException(status_code=404, detail="La Slice no existe.")
    
    slice_data = active_slices[slice_id]
    ruta = slice_data["ruta"]
    cir_util = slice_data["cir"]
    
    # Recuperamos la fórmula del 20% para devolver exactamente lo reservado
    req_cir_fisico = float(cir_util) * 1.2
    
    try:
        # El PCE suma los megas físicos de vuelta
        pce.liberar_networkinfo(ruta, req_cir_fisico)
        # El SRC borra la cola del router
        src.eliminar_comandos_router(slice_id, ruta)
        
        del active_slices[slice_id]
        print(f"[API] ✅ Slice {slice_id} eliminada correctamente.")
        return {"mensaje": "Recursos liberados correctamente"}
    except Exception as e:
        raise HTTPException(status_code=500, detail="Error interno al liberar la Slice.")