#!/usr/bin/env python3
import json
import subprocess

# MEMORIA GLOBAL: Evita que el router se formatee si ya tiene el �rbol base
nodos_inicializados = set()

def ejecutar(nodo, comando):
    """Inyecta un comando en el nodo contenedor usando lxc-attach"""
    cmd_lxc = f"sudo lxc-attach -n {nodo} -- {comando}"
    subprocess.run(cmd_lxc, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def check_containers_running(required_nodes):
    """Verifica si los contenedores requeridos est�n activos en el sistema"""
    try:
        result = subprocess.run(['sudo', 'lxc-ls', '--running'], capture_output=True, text=True)
        running_containers = result.stdout.split() if result.stdout else []
        return all(node in running_containers for node in required_nodes)
    except Exception as e:
        print(f"[SRC] Error al verificar contenedores: {e}")
        return False

def load_loopbacks(path='networkinfo.json'):
    """Carga los direcciones loopback (SID) de los nodos desde la configuraci�n de red"""
    try:
        with open(path, 'r') as f:
            data = json.load(f)
            return {n: lp.split('/').pop(0) for n, lp in data.get('loopbacks', {}).items()}
    except FileNotFoundError:
        return {}

def inicializar_qos_base_borde(nodo):
    """ Crea el tronco base en los routers de borde usando IFB0 y DRR nativo """
    global nodos_inicializados
    if nodo in nodos_inicializados:
        return # Si ya se inicializ�, saltamos para no borrar las Slices previas
    nodos_inicializados.add(nodo)

    cmds_base = [
        # 1. Preparar interfaces f�sicas (Sin Open vSwitch)
        "ip link set eth1 up 2>/dev/null",
        
        # 2. Crear y levantar la interfaz virtual IFB0
        "ip link add ifb0 type ifb 2>/dev/null",
        "ip link set dev ifb0 up 2>/dev/null",
        
        # 3. Redirigir el tr�fico Ingress de eth1 hacia ifb0 (Truco del Paper)
        "tc qdisc replace dev eth1 handle ffff: ingress 2>/dev/null",
        "tc filter replace dev eth1 parent ffff: matchall action mirred egress redirect dev ifb0 2>/dev/null",
        
        # 4. HTB global en ifb0 (Ingreso Granularidad Fina)
        "tc qdisc replace dev ifb0 root handle 1: htb default 10 2>/dev/null",
        "tc class replace dev ifb0 parent 1: classid 1:1 htb rate 1gbit 2>/dev/null",
        
        # 5. Tronco DRR principal en eth1 (Egreso Granularidad Fina)
        "tc qdisc replace dev eth1 root handle 10: drr 2>/dev/null",

        # 6. Granularidad Gruesa en eth2 y eth3
        "tc qdisc replace dev eth2 root handle 1: htb default 1 2>/dev/null",
        "tc class replace dev eth2 parent 1: classid 1:1 htb rate 1gbit 2>/dev/null",
        "tc qdisc replace dev eth2 parent 1:1 handle 2: prio 2>/dev/null",
        "tc qdisc replace dev eth2 parent 2:3 handle 20: drr 2>/dev/null",
        "tc class replace dev eth2 parent 20: classid 20:1 drr quantum 1538 2>/dev/null",
        "tc class replace dev eth2 parent 20: classid 20:2 drr quantum 1538 2>/dev/null",
        "tc class replace dev eth2 parent 20: classid 20:3 drr quantum 1538 2>/dev/null",

        "tc qdisc replace dev eth3 root handle 1: htb default 1 2>/dev/null",
        "tc class replace dev eth3 parent 1: classid 1:1 htb rate 1gbit 2>/dev/null",
        "tc qdisc replace dev eth3 parent 1:1 handle 2: prio 2>/dev/null",
        "tc qdisc replace dev eth3 parent 2:3 handle 20: drr 2>/dev/null",
        "tc class replace dev eth3 parent 20: classid 20:1 drr quantum 1538 2>/dev/null",
        "tc class replace dev eth3 parent 20: classid 20:2 drr quantum 1538 2>/dev/null",
        "tc class replace dev eth3 parent 20: classid 20:3 drr quantum 1538 2>/dev/null"
    ]
    for cmd in cmds_base:
        ejecutar(nodo, cmd)

def configurar_nodo_p(nodo):
    """Configura QoS de granularidad gruesa en nodos de tr�nsito"""
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
    """Crea dinámicamente IPs y marcado DSCP apilando los filtros correctamente"""
    cmds_gnb = [
        f"ip link add link eth1 name eth1.{vlan_id} type vlan id {vlan_id} 2>/dev/null",
        f"ip link add link eth2 name eth2.{vlan_id} type vlan id {vlan_id} 2>/dev/null",
        f"ip link set up eth1.{vlan_id}",
        f"ip link set up eth2.{vlan_id}",
        f"ip -6 addr add fd00:{vlan_id}:a::1/64 dev eth1.{vlan_id} 2>/dev/null",
        f"ip -6 addr add fd00:{vlan_id}:b::1/64 dev eth2.{vlan_id} 2>/dev/null",
        f"ip -6 rule add from fd00:{vlan_id}:a::/64 lookup {vlan_id} 2>/dev/null",
        f"ip -6 route add default via fd00:{vlan_id}:b::2 dev eth2.{vlan_id} table {vlan_id} 2>/dev/null",
        f"tc qdisc replace dev eth2.{vlan_id} root handle 1: prio 2>/dev/null"
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
        f"tc qdisc replace dev eth2.{vlan_id} root handle 1: prio 2>/dev/null"
    ]

    idx = 2
    for cls_name, cls_data in qos_classes.items():
        req_delay = float(cls_data.get("delay", 100))
        if req_delay <= 5: dscp_int = "0x30"
        elif req_delay <= 20: dscp_int = "0x26"
        elif req_delay <= 50: dscp_int = "0x12"
        else: dscp_int = "0x00"

        # IMPORTANTE: Usamos 'add' y 'prio {idx}' para que las reglas no se sobrescriban
        cmds_gnb.extend([
            f"ip -6 addr add fd00:{vlan_id}:a::{idx}/64 dev eth1.{vlan_id} 2>/dev/null",
            f"tc filter add dev eth2.{vlan_id} protocol ipv6 parent 1:0 prio {idx} u32 match ip6 src fd00:{vlan_id}:a::{idx} action pedit ex munge ip6 traffic_class set {dscp_int} pipe classid 1:1 2>/dev/null"
        ])
        cmds_upf.extend([
            f"ip -6 addr add fd00:{vlan_id}:d::{idx}/64 dev eth1.{vlan_id} 2>/dev/null",
            f"tc filter add dev eth2.{vlan_id} protocol ipv6 parent 1:0 prio {idx} u32 match ip6 src fd00:{vlan_id}:d::{idx} action pedit ex munge ip6 traffic_class set {dscp_int} pipe classid 1:1 2>/dev/null"
        ])
        idx += 1

    for cmd in cmds_gnb: ejecutar(nodo_cliente, cmd)
    for cmd in cmds_upf: ejecutar(nodo_servidor, cmd)

def configurar_routers_borde(vlan_id, req_cir_total, qos_classes, ruta_ida_sids, ruta_vuelta_sids, req_delay_min):
    """ Configura RG y RU blindando los filtros con prioridades únicas """
    iface_salida_rg = "eth3" if "fcff:4::1" in ruta_ida_sids else "eth2"
    iface_salida_ru = "eth3" if "fcff:4::1" in ruta_vuelta_sids else "eth2"
    
    # FIX: Sumamos 1 para esquivar el Root (1:1). 
    # VLAN 3001 será 1:2. VLAN 3002 será 1:3. ¡Cero colisiones!
    sub_clase = str(int(str(vlan_id)[-1]) + 1)
    
    req_burst_total = sum(int(cls_data.get("burst", 1500)) for cls_data in qos_classes.values())

    cmds_rg = [
        f"ip link add link eth1 name eth1.{vlan_id} type vlan id {vlan_id} 2>/dev/null",
        f"ip -6 addr add fd00:{vlan_id}:b::2/64 dev eth1.{vlan_id} 2>/dev/null",
        f"ip link set eth1.{vlan_id} up",
        f"ip -6 route replace fd00:{vlan_id}:a::/64 via fd00:{vlan_id}:b::1 dev eth1.{vlan_id}",
        f"ip -6 route replace fd00:{vlan_id}:d::/64 encap seg6 mode encap segs {ruta_ida_sids} dev {iface_salida_rg}",
        
        f"tc class replace dev ifb0 parent 1:1 classid 1:{sub_clase} htb rate {req_cir_total}mbit burst {req_burst_total}b",
        f"tc filter add dev ifb0 protocol 802.1Q parent 1:0 prio {sub_clase} flower vlan_id {vlan_id} classid 1:{sub_clase} 2>/dev/null",
        
        f"tc class replace dev eth1 parent 10: classid 10:{sub_clase} drr quantum 1538",
        f"tc qdisc replace dev eth1 parent 10:{sub_clase} handle {sub_clase}00: drr",
        f"tc filter add dev eth1 protocol 802.1Q parent 10:0 prio {sub_clase} flower vlan_id {vlan_id} classid 10:{sub_clase} 2>/dev/null"
    ]

    cmds_ru = [
        f"ip link add link eth1 name eth1.{vlan_id} type vlan id {vlan_id} 2>/dev/null",
        f"ip -6 addr add fd00:{vlan_id}:c::2/64 dev eth1.{vlan_id} 2>/dev/null",
        f"ip link set eth1.{vlan_id} up",
        f"ip -6 route replace fd00:{vlan_id}:d::/64 via fd00:{vlan_id}:c::1 dev eth1.{vlan_id}",
        f"ip -6 route replace fd00:{vlan_id}:a::/64 encap seg6 mode encap segs {ruta_vuelta_sids} dev {iface_salida_ru}",
        
        f"tc class replace dev ifb0 parent 1:1 classid 1:{sub_clase} htb rate {req_cir_total}mbit burst {req_burst_total}b",
        f"tc filter add dev ifb0 protocol 802.1Q parent 1:0 prio {sub_clase} flower vlan_id {vlan_id} classid 1:{sub_clase} 2>/dev/null",
        
        f"tc class replace dev eth1 parent 10: classid 10:{sub_clase} drr quantum 1538",
        f"tc qdisc replace dev eth1 parent 10:{sub_clase} handle {sub_clase}00: drr",
        f"tc filter add dev eth1 protocol 802.1Q parent 10:0 prio {sub_clase} flower vlan_id {vlan_id} classid 10:{sub_clase} 2>/dev/null"
    ]

    cola_hija_idx = 0
    cola_best_effort_ifb = None
    cola_best_effort_drr = None
    ultima_cola_ifb = None
    ultima_cola_drr = None

    for cls_name, cls_data in qos_classes.items():
        req_delay = float(cls_data.get("delay", 100))
        cir = cls_data.get("cir", 50)
        burst = cls_data.get("burst", 1500)

        if req_delay <= 5: dscp_int, dscp_ext = "0x30", "0x04"
        elif req_delay <= 20: dscp_int, dscp_ext = "0x26", "0x03"
        elif req_delay <= 50: dscp_int, dscp_ext = "0x12", "0x02"
        else: dscp_int, dscp_ext = "0x00", "0x01"

        cola_hija_ifb = f"1:{sub_clase}{cola_hija_idx}"
        cola_hija_drr = f"{sub_clase}00:{cola_hija_idx + 1}"
        
        # 2. FIX: Prioridad de filtro única basada en el índice de la cola
        prio_interna = cola_hija_idx + 1
        ultima_cola_ifb = cola_hija_ifb
        ultima_cola_drr = cola_hija_drr
        
        if req_delay > 50:
            cola_best_effort_ifb = cola_hija_ifb
            cola_best_effort_drr = cola_hija_drr

        cmds_rg.extend([
            f"tc class replace dev ifb0 parent 1:{sub_clase} classid {cola_hija_ifb} htb rate {cir}mbit burst {burst}b",
            f"tc filter add dev ifb0 protocol 802.1Q parent 1:{sub_clase} prio {prio_interna} u32 match ip6 priority {dscp_int} 0xff classid {cola_hija_ifb} 2>/dev/null",
            f"tc class replace dev eth1 parent {sub_clase}00: classid {cola_hija_drr} drr quantum 1538",
            f"tc filter add dev eth1 protocol 802.1Q parent {sub_clase}00:0 prio {prio_interna} u32 match ip6 priority {dscp_int} 0xff classid {cola_hija_drr} 2>/dev/null"
        ])
        cmds_ru.extend([
            f"tc class replace dev ifb0 parent 1:{sub_clase} classid {cola_hija_ifb} htb rate {cir}mbit burst {burst}b",
            f"tc filter add dev ifb0 protocol 802.1Q parent 1:{sub_clase} prio {prio_interna} u32 match ip6 priority {dscp_int} 0xff classid {cola_hija_ifb} 2>/dev/null",
            f"tc class replace dev eth1 parent {sub_clase}00: classid {cola_hija_drr} drr quantum 1538",
            f"tc filter add dev eth1 protocol 802.1Q parent {sub_clase}00:0 prio {prio_interna} u32 match ip6 priority {dscp_int} 0xff classid {cola_hija_drr} 2>/dev/null"
        ])

        if dscp_ext == "0x04":
            cmds_rg.append(f"tc filter add dev {iface_salida_rg} protocol ipv6 parent 2:0 prio {sub_clase}{prio_interna} u32 match ip6 priority {dscp_int} 0xff action pedit ex munge ip6 traffic_class set {dscp_ext} pipe classid 2:1 2>/dev/null")
            cmds_ru.append(f"tc filter add dev {iface_salida_ru} protocol ipv6 parent 2:0 prio {sub_clase}{prio_interna} u32 match ip6 priority {dscp_int} 0xff action pedit ex munge ip6 traffic_class set {dscp_ext} pipe classid 2:1 2>/dev/null")
        else:
            cola_drr_out = "20:1" if dscp_ext == "0x03" else ("20:2" if dscp_ext == "0x02" else "20:3")
            prio_filter = 2 if dscp_ext == "0x03" else (3 if dscp_ext == "0x02" else 4)
            prio_unica = int(f"{prio_filter}{sub_clase}{prio_interna}")
            cmds_rg.extend([
                f"tc filter add dev {iface_salida_rg} protocol ipv6 parent 2:0 prio {prio_unica} u32 match ip6 priority {dscp_int} 0xff classid 2:3 2>/dev/null",
                f"tc filter add dev {iface_salida_rg} protocol ipv6 parent 20:0 prio {prio_unica} u32 match ip6 priority {dscp_int} 0xff action pedit ex munge ip6 traffic_class set {dscp_ext} pipe classid {cola_drr_out} 2>/dev/null"
            ])
            cmds_ru.extend([
                f"tc filter add dev {iface_salida_ru} protocol ipv6 parent 2:0 prio {prio_unica} u32 match ip6 priority {dscp_int} 0xff classid 2:3 2>/dev/null",
                f"tc filter add dev {iface_salida_ru} protocol ipv6 parent 20:0 prio {prio_unica} u32 match ip6 priority {dscp_int} 0xff action pedit ex munge ip6 traffic_class set {dscp_ext} pipe classid {cola_drr_out} 2>/dev/null"
            ])

        cola_hija_idx += 1

    # 3. FIX: Aplicamos el recoge-basuras a AMBAS interfaces (ifb0 y eth1)
    dest_ifb = cola_best_effort_ifb if cola_best_effort_ifb else ultima_cola_ifb
    dest_drr = cola_best_effort_drr if cola_best_effort_drr else ultima_cola_drr

    cmds_rg.extend([
        f"tc filter add dev ifb0 protocol 802.1Q parent 1:{sub_clase} prio 99 u32 match u32 0 0 classid {dest_ifb} 2>/dev/null",
        f"tc filter add dev eth1 protocol 802.1Q parent {sub_clase}00:0 prio 99 u32 match u32 0 0 classid {dest_drr} 2>/dev/null"
    ])
    cmds_ru.extend([
        f"tc filter add dev ifb0 protocol 802.1Q parent 1:{sub_clase} prio 99 u32 match u32 0 0 classid {dest_ifb} 2>/dev/null",
        f"tc filter add dev eth1 protocol 802.1Q parent {sub_clase}00:0 prio 99 u32 match u32 0 0 classid {dest_drr} 2>/dev/null"
    ])

    for cmd in cmds_rg: ejecutar('rg', cmd)
    for cmd in cmds_ru: ejecutar('ru', cmd)

def inyectar_comandos_router(slice_id, req_cir_total, ruta_asignada, req_delay_min, qos_classes):
    """ Orquesta la red desde cero """
    print(f"\n[SRC] === INICIANDO APROVISIONAMIENTO ZTP (Zero-Touch) ===")
    print(f"[SRC] Slice: {slice_id} | CIR Total: {req_cir_total}Mbit | Ruta: {ruta_asignada}")

    if not check_containers_running(ruta_asignada):
        print(f"[SRC] L ERROR CR�TICO: Alg�n nodo de la ruta {ruta_asignada} ha ca�do en el �ltimo milisegundo.")
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

    print("[SRC] 1. Configurando �rboles base en routers de borde...")
    inicializar_qos_base_borde('rg')
    inicializar_qos_base_borde('ru')

    print("[SRC] 2. Configurando nodos de tr�nsito (Granularidad Gruesa)...")
    for nodo in ruta_asignada[1:-1]:
        configurar_nodo_p(nodo)

    print("[SRC] 3. Configurando extremos de acceso (VLAN, IPs, PBR y DSCP Int)...")
    configurar_extremos_acceso('rgnb', 'rupf', slice_id, qos_classes)

    print("[SRC] 4. Configurando QoS (Fina y Gruesa) y T�neles SRv6 en Borde...")
    configurar_routers_borde(slice_id, req_cir_total, qos_classes, ruta_ida_sids, ruta_vuelta_sids, req_delay_min)

    print("[SRC] === APROVISIONAMIENTO COMPLETADO ===")
    return True

def eliminar_comandos_router(slice_id, ruta_asignada):
    """ Des-aprovisiona la Slice de los routers físicos purgado colas de forma estricta. """
    print(f"\n[SRC] === INICIANDO TERMINACIÓN DE SLICE {slice_id} ===")
    
    # FIX: Utilizamos EXACTAMENTE la misma fórmula que en la creación
    sub_clase = str(int(str(slice_id)[-1]) + 1)

    # 1. LIMPIEZA EN LOS ROUTERS FRONTERA (rg y ru)
    cmds_limpieza_borde = [
        # A) Borrar filtros principales (Capa 2)
        f"tc filter del dev ifb0 protocol 802.1Q parent 1:0 prio {sub_clase} 2>/dev/null",
        f"tc filter del dev eth1 protocol 802.1Q parent 10:0 prio {sub_clase} 2>/dev/null",
        
        # B) Borrar filtros internos (Capa 3) anclados a la slice
        f"tc filter del dev ifb0 parent 1:{sub_clase} 2>/dev/null",
        f"tc filter del dev eth1 parent {sub_clase}00: 2>/dev/null",
        
        # C) Borrar el planificador DRR anclado en eth1 (Borra hijas en cascada)
        f"tc qdisc del dev eth1 parent 10:{sub_clase} 2>/dev/null",
    ]
    
    # D) NUEVO: Borrar EXPLÍCITAMENTE las clases hijas HTB en ifb0 antes del padre
    for i in range(10):
        cmds_limpieza_borde.append(f"tc class del dev ifb0 classid 1:{sub_clase}{i} 2>/dev/null")
        
    cmds_limpieza_borde.extend([
        # E) Borrar las Clases Padre (Ahora ifb0 sí permite borrarse porque está vacía)
        f"tc class del dev ifb0 classid 1:{sub_clase} 2>/dev/null",
        f"tc class del dev eth1 classid 10:{sub_clase} 2>/dev/null",
        
        # F) Borrar la interfaz nativa
        f"ip link del eth1.{slice_id} 2>/dev/null"
    ])

    for cmd in cmds_limpieza_borde:
        ejecutar('rg', cmd)
        ejecutar('ru', cmd)

    # 2. LIMPIEZA EN LOS EXTREMOS DE ACCESO (rgnb y rupf)
    cmds_rgnb = [
        f"ip -6 rule del from fd00:{slice_id}:a::/64 lookup {slice_id} 2>/dev/null",
        f"ip link del eth1.{slice_id} 2>/dev/null",
        f"ip link del eth2.{slice_id} 2>/dev/null"
    ]
    cmds_rupf = [
        f"ip -6 rule del from fd00:{slice_id}:d::/64 lookup {slice_id} 2>/dev/null",
        f"ip link del eth1.{slice_id} 2>/dev/null",
        f"ip link del eth2.{slice_id} 2>/dev/null"
    ]
    for cmd in cmds_rgnb:
        ejecutar('rgnb', cmd)
    for cmd in cmds_rupf:
        ejecutar('rupf', cmd)

    print(f"[SRC] ✅ Colas HTB (Ingress), DRR (Egress), filtros y subinterfaz VLAN {slice_id} destruidas correctamente.")
    return True
def actualizar_limite_global(limite_mbit):
    """ Ajusta dinámicamente el Policer Global (1:1) en ifb0 """
    cmd = f"tc class replace dev ifb0 parent 1: classid 1:1 htb rate {limite_mbit}mbit"
    ejecutar('rg', cmd)
    ejecutar('ru', cmd)