# 검색 접근 제어. "누가 무엇을 볼 수 있는가"를 한 곳에 모은다. (M12)
#
# ★ 이 마일스톤의 전제 두 문장 ★
#   1. 벡터 검색은 권한을 모른다. 임베딩 공간에는 "이건 A팀 것"이라는 개념이 없다.
#   2. RAG는 신뢰할 수 없는 텍스트를 프롬프트에 집어넣는 구조 그 자체다.
# 이 파일은 1번을 다루고, 2번(인젝션)은 graph.py의 프롬프트가 다룬다.
#
# ★ 설계 원칙 하나만 지키면 된다 ★
# **필터를 호출하는 쪽이 아니라 저장소 내부에서 강제한다.**
#   search(query, filter=None)   <- 언젠가 누가 빼먹고, 그 순간이 유출 사고다
#   search(query, principal)     <- 빼먹는 것이 문법적으로 불가능하다(TypeError)
# RAG 지식이 아니라 그냥 좋은 API 설계인데, 효과가 가장 큰 지점이 여기다.
from dataclasses import dataclass

# 모든 역할에게 열린 청크를 나타내는 값. allowed_roles를 비워두는 대신 이 값을 넣는다 —
# "빈 리스트"를 필터로 표현하려면 저장소마다 다른 특수 구문이 필요한데(Qdrant의
# IsEmpty, SQL의 cardinality=0), 센티넬 하나면 두 저장소가 같은 방식으로 다룬다.
PUBLIC_ROLE = "*"

# 인증이 없는 지금의 기본 테넌트. CLI 인입과 인증 없는 요청이 여기로 온다.
DEFAULT_TENANT = "default"


@dataclass(frozen=True)
class Principal:
    """요청자. "누구인가"가 아니라 **"무엇을 볼 수 있는가"** 만 담는다.

    ★ frozen=True인 이유 ★ 요청 처리 도중 권한이 바뀌면 안 된다. 어딘가에서
    principal.roles에 하나를 추가하는 코드가 생기는 순간, 그 경로만 권한이 넓어지고
    아무도 눈치채지 못한다. 불변이면 그 사고가 애초에 불가능하다.

    ★ 지금은 헤더에서 온다 = 사실상 인증이 없다 ★ 누구나 X-Tenant-Id를 바꿔 보낼 수
    있으므로 **이 상태는 보안이 아니라 배선일 뿐이다.** 실제 인증(JWT 검증 등)이
    들어갈 자리를 api/deps.py의 get_principal()에 주석으로 못 박아뒀다.
    """

    tenant_id: str = DEFAULT_TENANT
    # frozenset인 이유도 위와 같다 — list면 append로 조용히 넓어진다.
    roles: frozenset[str] = frozenset()

    @property
    def role_filter_values(self) -> list[str]:
        """필터에 넣을 역할 목록. 항상 PUBLIC_ROLE을 포함한다.

        공개 청크(allowed_roles=["*"])는 역할과 무관하게 보여야 하므로, 매칭 목록에
        센티넬을 늘 끼워 넣는다. 이걸 각 저장소가 따로 처리하게 두면 한쪽만 빠뜨린다.
        """
        return sorted({*self.roles, PUBLIC_ROLE})


# 인입 시 청크에 붙는 기본값. CLI로 넣는 저장소 문서는 전부 공개다.
DEFAULT_TENANT_ID = DEFAULT_TENANT
DEFAULT_ALLOWED_ROLES = [PUBLIC_ROLE]
