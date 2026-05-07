from fastapi import FastAPI, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import pce
import src_v5 as src # O import src según el nombre de tu archivo exacto
import subprocess

# Contador global de la red y registro de estado
vlan_global_counter = 3000
active_slices = {}

def check_containers_running(required_nodes):
    """Verifica si todos los contenedores requeridos están corriendo en el host"""
    try:
        result = subprocess.run(['sudo', 'lxc-ls', '--running'], capture_output=True, text=True)
        # Cambio vital: .split() a secas
        running_containers = result.stdout.split() if result.stdout else []
        return all(node in running_containers for node in required_nodes)
    except Exception as e:
        print(f"[API] Error al verificar contenedores: {e}")
        return False

app = FastAPI(title="Controlador SDN - Orquestador ZTP de Slices")

app.mount("/static", StaticFiles(directory="."), name="static")

@app.get("/", response_class=HTMLResponse)
async def serve_webpage():
    """ Sirve la interfaz gráfica en el navegador """
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return "<h1>Error: No se encuentra index.html</h1>"

@app.post("/provision_slice")
async def provision_slice(peticion: dict):
    global vlan_global_counter
    global active_slices
    
    print("\n[API] Recibida nueva petición ZTP de provisión de Slice...")
    
    # 0. Global Health Check
    topologia_completa = ['rg', 'r1', 'r2', 'r3', 'r4', 'r5', 'r6', 'r7', 'ru']
    if not check_containers_running(topologia_completa):
        print("[API] ❌ Rechazo instantáneo: La topología VNX no está operativa.")
        raise HTTPException(status_code=503, detail="Infraestructura VNX no operativa (nodos caídos).")

    # 1. Extracción de los parámetros
    slice_data = peticion.get("network_slice", {})
    qos_classes = slice_data.get("5G_qos_classes", {})

    if not qos_classes:
        raise HTTPException(status_code=400, detail="La Slice debe contener al menos una clase QoS.")

    req_cir_total = sum(cls.get("cir", 0) for cls in qos_classes.values())
    req_delay_min = min(cls.get("delay", 100) for cls in qos_classes.values())

    print(f"[API] Requisitos extraídos -> CIR Total: {req_cir_total} Mbps | Delay Mínimo: {req_delay_min} ms")

    # 2. Control de Admisión (PCE)
    G = pce.create_graph()
    ruta_asignada = pce.control_de_admision(G, "rg", "ru", req_cir_total, req_delay_min)

    if ruta_asignada:
        vlan_global_counter += 1
        vlan_asignada = str(vlan_global_counter)
        
        print(f"[API] ✅ Slice admitida. Se ha asignado la VLAN {vlan_asignada}")
        pce.actualizar_networkinfo(ruta_asignada, req_cir_total)
        
        exito = src.inyectar_comandos_router(vlan_asignada, req_cir_total, ruta_asignada, req_delay_min, qos_classes)
        
        if not exito:
            raise HTTPException(status_code=500, detail="Error de SO al inyectar comandos de red.")
        
        # REGISTRAR LA SLICE
        active_slices[vlan_asignada] = {
            "ruta": ruta_asignada,
            "cir": req_cir_total
        }
        
        return {
            "slice_id": vlan_asignada, 
            "ruta_elegida": ruta_asignada
        }
    else:
        print("[API] ❌ Petición rechazada por falta de recursos (Saturación).")
        raise HTTPException(status_code=406, detail="Saturación de la red: No hay recursos disponibles que cumplan el SLA.")

@app.delete("/delete_slice/{slice_id}")
async def delete_slice(slice_id: str):
    global active_slices
    
    if slice_id not in active_slices:
        raise HTTPException(status_code=404, detail="La Slice no existe o ya fue eliminada.")
    
    print(f"\n[API] Petición de eliminación recibida para la Slice {slice_id}")
    
    slice_data = active_slices[slice_id]
    ruta = slice_data["ruta"]
    cir = slice_data["cir"]
    
    # 1. Devolver recursos al PCE (Plano de Control)
    pce.liberar_networkinfo(ruta, cir)
    
    # 2. Ordenar al SRC borrar las colas y túneles (Plano de Datos)
    src.eliminar_comandos_router(slice_id, ruta)
    
    # 3. Borrar la Slice del registro activo de la API
    del active_slices[slice_id]
    
    print(f"[API] ✅ Slice {slice_id} eliminada. Recursos liberados para futuras peticiones.")
    return {"message": "Recursos liberados correctamente"}