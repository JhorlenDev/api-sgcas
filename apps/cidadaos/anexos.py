"""
Anexos do prontuário — RG, comprovante de residência, laudo.

O arquivo vai para o disco; no banco fica só o metadado, dentro do campo JSON
do cidadão. Guardar o binário no banco inflaria backup e replicação sem ganho.

Três cuidados que a implementação anterior tomava e foram mantidos:

1. **O caminho é reconstruído a partir dos identificadores**, nunca do que o
   cliente enviou. Confiar no nome recebido abriria travessia de diretório —
   um `../../` levaria a escrita para fora da pasta de armazenamento.
2. **O nome no disco é gerado**, não é o original. Nome de arquivo carrega dado
   pessoal com frequência ("RG da Maria.jpg").
3. **Imagem é recomprimida.** Além de economizar espaço, remove metadados EXIF —
   que costumam trazer a coordenada de onde a foto foi tirada.
"""
from __future__ import annotations

import io
import uuid
from pathlib import Path

from django.conf import settings
from PIL import Image

TIPOS_ACEITOS = {
    'image/jpeg': '.jpg',
    'image/png': '.png',
    'image/webp': '.webp',
    'application/pdf': '.pdf',
}
TAMANHO_MAXIMO = 25 * 1024 * 1024
LADO_MAXIMO = 2000
LADO_MINIATURA = 320


class ErroDeAnexo(ValueError):
    """Mensagem mostrável ao atendente."""


def _raiz() -> Path:
    return Path(settings.ARMAZENAMENTO_LOCAL)


def _pasta(cidadao_id: str) -> Path:
    # A pasta sai do id do cidadão, que é um UUID gerado por nós — não há como
    # o cliente influenciar o caminho.
    destino = _raiz() / 'cidadaos' / str(uuid.UUID(cidadao_id))
    destino.mkdir(parents=True, exist_ok=True)
    return destino


def _processar_imagem(conteudo: bytes) -> tuple[bytes, bytes]:
    """Devolve a imagem recomprimida e a miniatura, ambas sem metadados."""
    with Image.open(io.BytesIO(conteudo)) as imagem:
        imagem = imagem.convert('RGB')
        imagem.thumbnail((LADO_MAXIMO, LADO_MAXIMO))

        principal = io.BytesIO()
        imagem.save(principal, format='JPEG', quality=85, optimize=True)

        imagem.thumbnail((LADO_MINIATURA, LADO_MINIATURA))
        miniatura = io.BytesIO()
        imagem.save(miniatura, format='JPEG', quality=75, optimize=True)

    return principal.getvalue(), miniatura.getvalue()


def guardar(cidadao_id: str, arquivo, tipo_documento: str) -> dict:
    if arquivo.size > TAMANHO_MAXIMO:
        raise ErroDeAnexo('Arquivo maior que 25 MB')

    tipo = (arquivo.content_type or '').lower()
    if tipo not in TIPOS_ACEITOS:
        raise ErroDeAnexo('Formato não aceito. Envie JPG, PNG, WEBP ou PDF.')

    conteudo = arquivo.read()
    anexo_id = str(uuid.uuid4())
    pasta = _pasta(cidadao_id)

    if tipo == 'application/pdf':
        nome = f'{anexo_id}.pdf'
        (pasta / nome).write_bytes(conteudo)
        miniatura = None
        tamanho = len(conteudo)
    else:
        try:
            principal, mini = _processar_imagem(conteudo)
        except Exception as erro:
            raise ErroDeAnexo('Não foi possível ler a imagem enviada') from erro

        nome = f'{anexo_id}.jpg'
        (pasta / nome).write_bytes(principal)
        miniatura = f'{anexo_id}_min.jpg'
        (pasta / miniatura).write_bytes(mini)
        tamanho = len(principal)
        tipo = 'image/jpeg'

    return {
        'id': anexo_id,
        'tipo_documento': tipo_documento,
        'arquivo': nome,
        'miniatura': miniatura,
        'mime': tipo,
        'tamanho': tamanho,
    }


def caminho(cidadao_id: str, anexo: dict, miniatura: bool = False) -> Path:
    """
    Caminho absoluto do anexo, reconstruído dos identificadores.

    O nome do arquivo vem do metadado gravado por nós, e a resolução final é
    conferida contra a pasta do cidadão: mesmo que o metadado fosse adulterado,
    a leitura não escaparia do diretório.
    """
    nome = anexo.get('miniatura') if miniatura else anexo.get('arquivo')
    if not nome:
        raise ErroDeAnexo('Anexo sem arquivo correspondente')

    pasta = _pasta(cidadao_id).resolve()
    destino = (pasta / Path(nome).name).resolve()
    if not str(destino).startswith(str(pasta)):
        raise ErroDeAnexo('Caminho de anexo inválido')
    if not destino.exists():
        raise ErroDeAnexo('Arquivo não encontrado no armazenamento')
    return destino


def remover(cidadao_id: str, anexo: dict) -> None:
    for chave in ('arquivo', 'miniatura'):
        nome = anexo.get(chave)
        if not nome:
            continue
        alvo = _pasta(cidadao_id) / Path(nome).name
        alvo.unlink(missing_ok=True)
