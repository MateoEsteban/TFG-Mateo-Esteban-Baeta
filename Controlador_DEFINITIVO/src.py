#!/usr/bin/env python3
import json
import subprocess

def ejecutar(nodo, comando):
    """Inyecta un comando en el nodo contenedor usando lxc-attach"""
    cmd_lxc = f"sudo lxc-attach -n {nodo} -- {comando}"
    subprocess.run(cmd_lxc, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def check_containers_running(required_nodes):
    """Verifica si todos los contenedores requeridos están corriendo"""
    try:
        result = subprocess.run(['sudo', 'lxc-ls', '--running'], capture_output=True, text=True)
        running_containers = result.stdout.split() if result.stdout else []
        return all(node in running_containers for node in required_nodes)
    except Exception as e:
        print(f"[SRC] Error al verificar contenedores: {e}")
        return False

def load_loopbacks(path='networkinfo.json'):
    """Carga los SIDs (loopbacks) de la red (sin máscara)"""
    try:
        with open(path, 'r') as f:
            data = json.load(f)
        return {n: lp.split('/').pop(0) for n, lp in data.get('loopbacks', {}).items()}
    except FileNotFoundError:
        return {}

def inicializar_qos_base_borde(nodo):
    """ Crea el tronco base (HTB y DRR) en los routers de borde (rg y ru). """
    cmds_base = [
        "ovs-vsctl add-br br0 2>/dev/null",
        "ovs-vsctl add-port br0 eth1 2>/dev/null",
        "ovs-vsctl add-port br0 int0 -- set interface int0 type=internal 2>/dev/null",
        "ip link set int0 up 2>/dev/null",
        "ip link set br0 up 2>/dev/null",
        "tc qdisc add dev int0 root handle 1: htb default 10 2>/dev/null",
        "tc class add dev int0 parent 1: classid 1:1 htb rate 1gbit 2>/dev/null",
        "tc qdisc add dev eth2 root handle 1: htb default 1 2>/dev/null",
        "tc class add dev eth2 parent 1: classid 1:1 htb rate 1gbit 2>/dev/null",
        "tc qdisc add dev eth2 parent 1:1 handle 2: prio 2>/dev/null",
        "tc qdisc add dev eth2 parent 2:3 handle 20: drr 2>/dev/null",
        "tc class add dev eth2 parent 20: classid 20:1 drr quantum 1538 2>/dev/null",
        "tc class add dev eth2 parent 20: classid 20:2 drr quantum 1538 2>/dev/null",
        "tc class add dev eth2 parent 20: classid 20:3 drr quantum 1538 2>/dev/null",
        "tc qdisc add dev eth3 root handle 1: htb default 1 2>/dev/null",
        "tc class add dev eth3 parent 1: classid 1:1 htb rate 1gbit 2>/dev/null",
        "tc qdisc add dev eth3 parent 1:1 handle 2: prio 2>/dev/null",
        "tc qdisc add dev eth3 parent 2:3 handle 20: drr 2>/dev/null",
        "tc class add dev eth3 parent 20: classid 20:1 drr quantum 1538 2>/dev/null",
        "tc class add dev eth3 parent 20: classid 20:2 drr quantum 1538 2>/dev/null",
        "tc class add dev eth3 parent 20: classid 20:3 drr quantum 1538 2>/dev/null"
    ]
    for cmd in cmds_base:
        ejecutar(nodo, cmd)

def configurar_nodo_p(nodo):
    """ Configuración de Granularidad Gruesa para los nodos de tránsito. """
    interfaces = ['eth1', 'eth2', 'eth3']
    for dev in interfaces:
        comandos = [
            f"tc qdisc add dev {dev} root handle 1: htb 2>/dev/null",
            f"tc class replace dev {dev} parent 1: classid 1:1 htb rate 1gbit",
            f"tc qdisc replace dev {dev} parent 1:1 handle 2: prio",
            f"tc qdisc replace dev {dev} parent 2:3 handle 20: drr",
            f"tc class replace dev {dev} parent 20: classid 20:1 drr quantum 1538",
            f"tc class replace dev {dev} parent 20: classid 20:2 drr quantum 1538",
            f"tc class replace dev {dev} parent 20: classid 20:3 drr quantum 1538",
            f"tc filter replace dev {dev} protocol ipv6 parent 2:0 prio 1 u32 match ip6 priority 0x04 0xff classid 2:1",
            f"tc filter replace dev {dev} protocol ipv6 parent 20:0 prio 1 u32 match ip6 priority 0x03 0xff classid 20:1",
            f"tc filter replace dev {dev} protocol ipv6 parent 20:0 prio 2 u32 match ip6 priority 0x02 0xff classid 20:2",
            f"tc filter replace dev {dev} protocol ipv6 parent 20:0 prio 3 u32 match ip6 priority 0x01 0xff classid 20:3"
        ]
        for cmd in comandos:
            ejecutar(nodo, cmd)

def configurar_extremos_acceso(nodo_cliente, nodo_servidor, vlan_id, qos_classes):
    """ Crea dinámicamente IPs y marcado DSCP para N flujos """
    cmds_gnb = [
        f"ip link add link eth1 name eth1.{vlan_id} type vlan id {vlan_id} 2>/dev/null",
        f"ip link add link eth2 name eth2.{vlan_id} type vlan id {vlan_id} 2>/dev/null",
        f"ip link set up eth1.{vlan_id}",
        f"ip link set up eth2.{vlan_id}",
        f"ip -6 addr add fd00:{vlan_id}:a::1/64 dev eth1.{vlan_id} 2>/dev/null",
        f"ip -6 addr add fd00:{vlan_id}:b::1/64 dev eth2.{vlan_id} 2>/dev/null",
        f"ip -6 rule add from fd00:{vlan_id}:a::/64 lookup {vlan_id} 2>/dev/null",
        f"ip -6 route add default via fd00:{vlan_id}:b::2 dev eth2.{vlan_id} table {vlan_id} 2>/dev/null",
        f"tc qdisc add dev eth2.{vlan_id} root handle 1: prio 2>/dev/null"
    ]
    
    cmds_upf = [
        f"ip link add link eth1 name eth1.{vlan_id} type vlan id {vlan_id} 2>/dev/null",
        f"ip link add link eth2 name eth2.{vlan_id} type vlan id {vlan_id} 2>/dev/null",
        f"ip link set up eth1.{vlan_id}",
        f"ip link set up eth2.{vlan_id}",
        f"ip -6 addr add fd00:{vlan_id}:d::1/64 dev eth1.{vlan_id} 2>/dev/null",
        f"ip -6 addr add fd00:{vlan_id}:c::1/64 dev eth2.{vlan_id} 2>/dev/null",
        f"ip -6 rule add from fd00:{vlan_id}:d::/64 lookup {vlan_id} 2>/dev/null",
        f"ip -6 route add default via fd00:{vlan_id}:c::2 dev eth2.{vlan_id} table {vlan_id} 2>/dev/null",
        f"tc qdisc add dev eth2.{vlan_id} root handle 1: prio 2>/dev/null"
    ]

    idx = 2
    for cls_name, cls_data in qos_classes.items():
        req_delay = float(cls_data.get("delay", 100))
        if req_delay <= 5:
            dscp_int = "0x30"
        elif req_delay <= 20:
            dscp_int = "0x26"
        elif req_delay <= 50:
            dscp_int = "0x12"
        else:
            dscp_int = "0x00"

        cmds_gnb.extend([
            f"ip -6 addr add fd00:{vlan_id}:a::{idx}/64 dev eth1.{vlan_id} 2>/dev/null",
            f"tc filter replace dev eth2.{vlan_id} protocol ipv6 parent 1:0 prio 4 u32 match ip6 src fd00:{vlan_id}:a::{idx} action pedit ex munge ip6 traffic_class set {dscp_int} pipe classid 1:1"
        ])
        cmds_upf.extend([
            f"ip -6 addr add fd00:{vlan_id}:d::{idx}/64 dev eth1.{vlan_id} 2>/dev/null",
            f"tc filter replace dev eth2.{vlan_id} protocol ipv6 parent 1:0 prio 4 u32 match ip6 src fd00:{vlan_id}:d::{idx} action pedit ex munge ip6 traffic_class set {dscp_int} pipe classid 1:1"
        ])
        idx += 1

    for cmd in cmds_gnb:
        ejecutar(nodo_cliente, cmd)
    for cmd in cmds_upf:
        ejecutar(nodo_servidor, cmd)

def configurar_routers_borde(vlan_id, req_cir_total, qos_classes, ruta_ida_sids, ruta_vuelta_sids, req_delay_min):
    """ Configura RG y RU mapeando a IDs de cola normales infiriendo el comportamiento """
    iface_salida_rg = "eth3" if "fcff:4::1" in ruta_ida_sids else "eth2"
    iface_salida_ru = "eth3" if "fcff:4::1" in ruta_vuelta_sids else "eth2"
    sub_clase = str(vlan_id)[-1]
    
    cmds_rg = [
        f"ip link add link int0 name int0.{vlan_id} type vlan id {vlan_id} 2>/dev/null",
        f"ip -6 addr add fd00:{vlan_id}:b::2/64 dev int0.{vlan_id} 2>/dev/null",
        f"ip link set int0.{vlan_id} up",
        f"ip -6 route replace fd00:{vlan_id}:a::/64 via fd00:{vlan_id}:b::1 dev int0.{vlan_id}",
        f"ip -6 route replace fd00:{vlan_id}:d::/64 encap seg6 mode encap segs {ruta_ida_sids} dev {iface_salida_rg}",
        f"tc class replace dev int0 parent 1:1 classid 1:{sub_clase} htb rate {req_cir_total}mbit",
        f"tc filter replace dev int0 protocol 802.1Q parent 1:0 prio 1 flower vlan_id {vlan_id} classid 1:{sub_clase}"
    ]
    cmds_ru = [
        f"ip link add link int0 name int0.{vlan_id} type vlan id {vlan_id} 2>/dev/null",
        f"ip -6 addr add fd00:{vlan_id}:c::2/64 dev int0.{vlan_id} 2>/dev/null",
        f"ip link set int0.{vlan_id} up",
        f"ip -6 route replace fd00:{vlan_id}:d::/64 via fd00:{vlan_id}:c::1 dev int0.{vlan_id}",
        f"ip -6 route replace fd00:{vlan_id}:a::/64 encap seg6 mode encap segs {ruta_vuelta_sids} dev {iface_salida_ru}",
        f"tc class replace dev int0 parent 1:1 classid 1:{sub_clase} htb rate {req_cir_total}mbit",
        f"tc filter replace dev int0 protocol 802.1Q parent 1:0 prio 1 flower vlan_id {vlan_id} classid 1:{sub_clase}"
    ]

    cola_hija_idx = 0
    for cls_name, cls_data in qos_classes.items():
        req_delay = float(cls_data.get("delay", 100))
        cir = cls_data.get("cir", 50)
        
        if req_delay <= 5:
            dscp_int, dscp_ext = "0x30", "0x04"
        elif req_delay <= 20:
            dscp_int, dscp_ext = "0x26", "0x03"
        elif req_delay <= 50:
            dscp_int, dscp_ext = "0x12", "0x02"
        else:
            dscp_int, dscp_ext = "0x00", "0x01"

        cola_hija = f"1:{sub_clase}{cola_hija_idx}"
        
        cmds_rg.extend([
            f"tc class replace dev int0 parent 1:{sub_clase} classid {cola_hija} htb rate {cir}mbit",
            f"tc filter replace dev int0 protocol 802.1Q parent 1:{sub_clase} prio 1 u32 match ip6 priority {dscp_int} 0xff classid {cola_hija}"
        ])
        cmds_ru.extend([
            f"tc class replace dev int0 parent 1:{sub_clase} classid {cola_hija} htb rate {cir}mbit",
            f"tc filter replace dev int0 protocol 802.1Q parent 1:{sub_clase} prio 1 u32 match ip6 priority {dscp_int} 0xff classid {cola_hija}"
        ])

        if dscp_ext == "0x04":
            cmds_rg.append(f"tc filter replace dev {iface_salida_rg} protocol ipv6 parent 2:0 prio 1 u32 match ip6 priority {dscp_int} 0xff action pedit ex munge ip6 traffic_class set {dscp_ext} classid 2:1")
            cmds_ru.append(f"tc filter replace dev {iface_salida_ru} protocol ipv6 parent 2:0 prio 1 u32 match ip6 priority {dscp_int} 0xff action pedit ex munge ip6 traffic_class set {dscp_ext} classid 2:1")
        else:
            cola_drr = "20:1" if dscp_ext == "0x03" else ("20:2" if dscp_ext == "0x02" else "20:3")
            prio_filter = 2 if dscp_ext == "0x03" else (3 if dscp_ext == "0x02" else 4)
            
            cmds_rg.extend([
                f"tc filter replace dev {iface_salida_rg} protocol ipv6 parent 2:0 prio 2 u32 match ip6 priority {dscp_int} 0xff classid 2:3",
                f"tc filter replace dev {iface_salida_rg} protocol ipv6 parent 20:0 prio {prio_filter} u32 match ip6 priority {dscp_int} 0xff action pedit ex munge ip6 traffic_class set {dscp_ext} classid {cola_drr}"
            ])
            cmds_ru.extend([
                f"tc filter replace dev {iface_salida_ru} protocol ipv6 parent 2:0 prio 2 u32 match ip6 priority {dscp_int} 0xff classid 2:3",
                f"tc filter replace dev {iface_salida_ru} protocol ipv6 parent 20:0 prio {prio_filter} u32 match ip6 priority {dscp_int} 0xff action pedit ex munge ip6 traffic_class set {dscp_ext} classid {cola_drr}"
            ])
        cola_hija_idx += 1

    for cmd in cmds_rg:
        ejecutar('rg', cmd)
    for cmd in cmds_ru:
        ejecutar('ru', cmd)

def inyectar_comandos_router(slice_id, req_cir_total, ruta_asignada, req_delay_min, qos_classes):
    """ Orquesta la red desde cero con colas secuenciales normales """
    print(f"\n[SRC] === INICIANDO APROVISIONAMIENTO ZTP (Zero-Touch) ===")
    print(f"[SRC] Slice: {slice_id} | CIR Total: {req_cir_total}Mbit | Ruta: {ruta_asignada}")
    
    if not check_containers_running(ruta_asignada):
        print(f"[SRC] ❌ ERROR CRÍTICO: Algún nodo de la ruta {ruta_asignada} ha caído en el último milisegundo.")
        return False
        
    loopbacks = load_loopbacks()
    if not loopbacks:
        print("[SRC] ERROR: No se pudieron cargar los loopbacks.")
        return False

    sids_ida = [loopbacks[nodo] for nodo in ruta_asignada[1:]]
    ruta_ida_sids = ",".join(sids_ida)

    ruta_vuelta = ruta_asignada[::-1]
    sids_vuelta = [loopbacks[nodo] for nodo in ruta_vuelta[1:]]
    ruta_vuelta_sids = ",".join(sids_vuelta)

    print("[SRC] 1. Configurando árboles base en routers de borde...")
    inicializar_qos_base_borde('rg')
    inicializar_qos_base_borde('ru')

    print("[SRC] 2. Configurando nodos de tránsito (Granularidad Gruesa)...")
    for nodo in ruta_asignada[1:-1]:
        configurar_nodo_p(nodo)

    print("[SRC] 3. Configurando extremos de acceso (VLAN, IPs, PBR y DSCP Int)...")
    configurar_extremos_acceso('rgnb', 'rupf', slice_id, qos_classes)

    print("[SRC] 4. Configurando QoS (Fina y Gruesa) y Túneles SRv6 en Borde...")
    configurar_routers_borde(slice_id, req_cir_total, qos_classes, ruta_ida_sids, ruta_vuelta_sids, req_delay_min)

    print("[SRC] === APROVISIONAMIENTO COMPLETADO ===")
    return True

# NUEVO BLOQUE: Función para limpiar el router
def eliminar_comandos_router(slice_id, ruta_asignada):
    """
    Des-aprovisiona la Slice de los routers físicos.
    Borra las interfaces VLAN, rutas SRv6 y las colas HTB asociadas.
    """
    print(f"\n[SRC] === INICIANDO TERMINACIÓN DE SLICE {slice_id} ===")
    
    sub_clase = str(slice_id)[-1]
    
    # 1. Limpiar Extremos (Cliente gNB y Servidor UPF)
    ejecutar('rgnb', f"ip link del eth1.{slice_id} 2>/dev/null")
    ejecutar('rgnb', f"ip link del eth2.{slice_id} 2>/dev/null")
    ejecutar('rupf', f"ip link del eth1.{slice_id} 2>/dev/null")
    ejecutar('rupf', f"ip link del eth2.{slice_id} 2>/dev/null")
    
    # 2. Limpiar Routers de Borde (RG y RU)
    ejecutar('rg', f"ip link del int0.{slice_id} 2>/dev/null")
    ejecutar('ru', f"ip link del int0.{slice_id} 2>/dev/null")
    
    ejecutar('rg', f"ip -6 route del fd00:{slice_id}:d::/64 2>/dev/null")
    ejecutar('ru', f"ip -6 route del fd00:{slice_id}:a::/64 2>/dev/null")
    
    ejecutar('rg', f"tc class del dev int0 classid 1:{sub_clase} 2>/dev/null")
    ejecutar('ru', f"tc class del dev int0 classid 1:{sub_clase} 2>/dev/null")
    
    print(f"[SRC] ✅ Slice {slice_id} eliminada físicamente del plano de datos.")
    return True