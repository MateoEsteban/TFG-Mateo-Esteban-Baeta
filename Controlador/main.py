from fastapi import FastAPI, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import pce
import src
import subprocess

vlan_global_counter = 3000
active_slices = {}  # Diccionario para almacenar el estado de las slices activas

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

    # Añadimos un 20% de overhead para considerar las cabeceras SRv6 e IPv6
    req_cir_fisico = req_cir_total * 1.2

    print(f"[API] Requisitos -> CIR Útil (HTB): {req_cir_total} Mbps | CIR Físico (Topología): {req_cir_fisico} Mbps")

    G = pce.create_graph()
    # El PCE busca una ruta con suficientes recursos físicos considerando el overhead
    ruta_asignada = pce.control_de_admision(G, "rg", "ru", req_cir_fisico, req_delay_min)

    # Procesamiento de la respuesta del control de admisión
    if ruta_asignada:
        # Asignar un identificador VLAN único para la slice
        vlan_global_counter += 1
        vlan_asignada = str(vlan_global_counter)
        print(f"[API] ✅ Slice admitida. Se ha asignado la VLAN {vlan_asignada}")

        # Almacenar la información de la slice en la memoria del controlador
        active_slices[vlan_asignada] = {
            "ruta": ruta_asignada,
            "cir": req_cir_total
        }

        # Actualizar los recursos disponibles en la topología de red
        pce.actualizar_networkinfo(ruta_asignada, req_cir_total)

        # Inyectar la configuración de la slice en los routers especificados
        exito = src.inyectar_comandos_router(vlan_asignada, req_cir_total, ruta_asignada, req_delay_min, qos_classes)

        if not exito:
            raise HTTPException(status_code=500, detail="Error en la configuración de routers.")

        return {"slice_id": vlan_asignada, "ruta_elegida": ruta_asignada}
    else:
        raise HTTPException(status_code=406, detail="Saturación: No hay recursos físicos suficientes.")


@app.delete("/delete_slice/{slice_id}")
async def delete_slice(slice_id: str):
    global active_slices
    
    # Verificar que la slice existe en la memoria del controlador
    if slice_id not in active_slices:
        raise HTTPException(status_code=404, detail="La Slice no existe en la memoria.")
        
    slice_data = active_slices[slice_id]
    ruta = slice_data["ruta"]
    cir_util = slice_data["cir"]
    
    # Calcular los recursos físicos que se deben liberar (incluyendo overhead)
    req_cir_fisico = float(cir_util) * 1.2
    
    try:
        # Liberar los recursos en el grafo de la topología
        pce.liberar_networkinfo(ruta, req_cir_fisico)
        
        # Eliminar la configuración de la slice de los routers
        src.eliminar_comandos_router(slice_id, ruta)
        
        # Remover la slice de la memoria del controlador
        if slice_id in active_slices:
            del active_slices[slice_id]
            
        print(f"[API] ✅ Slice {slice_id} eliminada completamente de la red y la memoria.")
        return {"mensaje": f"Recursos de la VLAN {slice_id} liberados correctamente"}
        
    except Exception as e:
        # Log detallado del error para facilitar el diagnóstico
        print(f"\n[API] ❌ Error durante la eliminación de la slice: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error interno del controlador: {str(e)}")