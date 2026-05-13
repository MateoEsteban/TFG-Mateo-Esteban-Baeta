#!/usr/bin/env python3
import json
import networkx as nx

def create_graph():
    with open("networkinfo.json", "r") as f:
        data = json.load(f)
    
    G = nx.DiGraph()
    for n in data["graph"]["nodes"]:
        G.add_node(n)
    
    for e in data["graph"]["edges"]:
        G.add_edge(e["source"], e["target"], bandwidth=e["bandwidth"], delay=e["delay"])
    
    return G

def control_de_admision(G, origen, destino, req_cir, req_delay):
    """
    Comprueba si existe algún camino en el grafo que soporte los requisitos 
    de ancho de banda y latencia máxima usando NetworkX.
    """
    print(f"\n[PCE] Ejecutando Control de Admisión -> Requisitos: {req_cir} Mbps | Latencia Máx: {req_delay} ms")
    
    try:
        caminos_posibles = list(nx.all_simple_paths(G, source=origen, target=destino))
    except nx.NetworkXNoPath:
        print("❌ [PCE] Error: No existe conectividad física entre el origen y el destino.")
        return None

    caminos_posibles.sort(key=lambda c: sum(G[c[i]][c[i+1]]['delay'] for i in range(len(c)-1)))
    
    for camino in caminos_posibles:
        delay_total = 0
        bw_minimo = float('inf')
        
        for i in range(len(camino)-1):
            u, v = camino[i], camino[i+1]
            delay_total += G[u][v]['delay']
            bw_minimo = min(bw_minimo, G[u][v]['bandwidth'])
            
        if delay_total <= req_delay and bw_minimo >= req_cir:
            print(f"✅ [PCE] ¡ACEPTADO! Ruta válida encontrada: {camino}")
            print(f" -> Rendimiento proyectado de la ruta: Latencia {delay_total}ms | BW Mínimo {bw_minimo}Mbps")
            return camino
            
    print("❌ [PCE] DESESTIMADA. Ningún camino en la red dispone de los recursos suficientes para el SLA.")
    return None

def actualizar_networkinfo(ruta_asignada, req_cir, archivo="networkinfo.json"):
    """
    Actualizar el estado de la red. Resta el ancho de banda concedido 
    a los enlaces de la ruta elegida y sobrescribe el fichero JSON.
    """
    print(f"\n[PCE] Actualizando el estado de la red en '{archivo}'...")
    with open(archivo, "r") as f:
        data = json.load(f)

    for i in range(len(ruta_asignada) - 1):
        origen = ruta_asignada[i]
        destino = ruta_asignada[i+1]
        for enlace in data["graph"]["edges"]:
            if enlace["source"] == origen and enlace["target"] == destino:
                enlace["bandwidth"] -= req_cir
                print(f" -> Enlace actualizado ({origen} -> {destino}): Nuevo ancho de banda libre = {enlace['bandwidth']} Mbps")
                break

    with open(archivo, "w") as f:
        json.dump(data, f, indent=4)
        
    print("[PCE] ✅ Archivo JSON sobrescrito correctamente.")

def liberar_networkinfo(ruta_asignada, req_cir_fisico, archivo="networkinfo.json"):
    """
    Restaura el estado de la red sumando el CIR físico liberado a los enlaces de la ruta.
    """
    print(f"\n[PCE] Devolviendo {req_cir_fisico} Mbps a los enlaces físicos en '{archivo}'...")
    with open(archivo, "r") as f:
        data = json.load(f)

    for i in range(len(ruta_asignada) - 1):
        origen = ruta_asignada[i]
        destino = ruta_asignada[i+1]
        for enlace in data["graph"]["edges"]:
            if enlace["source"] == origen and enlace["target"] == destino:
                enlace["bandwidth"] += req_cir_fisico
                break

    with open(archivo, "w") as f:
        json.dump(data, f, indent=4)
    print("[PCE] ✅ Archivo JSON restaurado con éxito.")
    
if __name__ == "__main__":
    print("[PCE] Iniciando prueba local del PCE (Sin API)...")
    G = create_graph()
    req_cir = 100
    req_delay = 5
    ruta = control_de_admision(G, "rg", "ru", req_cir, req_delay)
    if ruta:
        actualizar_networkinfo(ruta, req_cir)
    print(f"[PCE] Prueba finalizada. Ruta asignada: {ruta}")