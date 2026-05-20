#!/usr/bin/env python3
import json
import networkx as nx

def create_graph():
    """
    Crea un grafo dirigido a partir de la configuración de red en networkinfo.json.
    Los nodos representan routers y los enlaces incluyen información de ancho de banda y latencia.
    """
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
    Verifica si existe una ruta disponible que cumpla los requisitos
    de ancho de banda y latencia máxima utilizando Networkx.

    Devuelve la ruta (lista de nodos) si cumple los requisitos, None si no hay ruta disponible.
    """
    print(f"\n[PCE] Ejecutando Control de Admisión -> Requisitos: {req_cir} Mbps | Latencia Máx: {req_delay} ms")

    try:
        # Obtener todos los caminos posibles
        caminos = list(nx.all_simple_paths(G, source=origen, target=destino))
    except nx.NetworkXNoPath:
        return None

    caminos_validos = []

    # Evaluar restricciones de SLA en cada ruta
    for camino in caminos:
        delay_total = 0
        bw_minimo = float('inf')

        # Extraer métricas del camino candidato
        for i in range(len(camino) - 1):
            u, v = camino[i], camino[i+1]
            delay_total += G[u][v]['delay']
            bw_minimo = min(bw_minimo, G[u][v]['bandwidth'])

        # Validacion estricta: Si cumple, guardamos la tupla con TRES elementos
        if delay_total <= req_delay and bw_minimo >= req_cir:
            caminos_validos.append((camino, delay_total, bw_minimo))

    # Si ningún camino superó el filtro, se rechaza la petición
    if not caminos_validos:
        print("❌ [PCE] DESESTIMADA. Ningún camino en la red dispone de los recursos suficientes para el SLA.")
        return None

    # Ordenar solo los caminos válidos por latencia (índice 1 de la tupla)
    caminos_validos.sort(key=lambda x: x[1])

    # Desempaquetar los TRES valores directamente del ganador (sin recalcular nada)
    mejor_ruta, mejor_delay, bw_minimo_mejor = caminos_validos[0]
    
    print(f"✅ [PCE] ¡ACEPTADO! Ruta válida encontrada: {mejor_ruta}")
    print(f" -> Rendimiento proyectado de la ruta: Latencia {mejor_delay}ms | BW Mínimo {bw_minimo_mejor}Mbps")
    
    return mejor_ruta

def actualizar_networkinfo(ruta_asignada, req_cir, archivo="networkinfo.json"):
    """
    Actualizar el estado de la topología de red. Decrementa el ancho de banda
    disponible en los enlaces correspondientes a la ruta asignada.
    
    Persiste los cambios en el archivo JSON.
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
    """ Restaura el estado de la red sumando el CIR físico liberado a los enlaces de la ruta. """
    print(f"\n[PCE] Devolviendo {req_cir_fisico} Mbps a los enlaces físicos en '{archivo}'...")
    
    with open(archivo, "r") as f:
        data = json.load(f)
        
    # Recorrer la ruta y devolver los megas a cada salto
    for i in range(len(ruta_asignada) - 1):
        origen = ruta_asignada[i]
        destino = ruta_asignada[i+1]
        
        for enlace in data["graph"]["edges"]:
            if enlace["source"] == origen and enlace["target"] == destino:
                enlace["bandwidth"] += req_cir_fisico
                print(f" -> Enlace restaurado ({origen} -> {destino}): Nuevo ancho de banda libre = {enlace['bandwidth']} Mbps")
                break
                
    # Sobrescribir el archivo JSON con los recursos recuperados
    with open(archivo, "w") as f:
        json.dump(data, f, indent=4)
        
    print("[PCE] ✅ Archivo JSON sobrescrito y recursos liberados correctamente.")
