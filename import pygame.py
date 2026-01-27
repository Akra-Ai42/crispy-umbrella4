import pygame
import math

# ==========================================================
# 1. DÉMARRAGE DE PYGAME
# ==========================================================
# Pygame est une bibliothèque qui permet d'afficher une fenêtre
# et d'y dessiner des formes en mouvement.

pygame.init()

# Taille de la fenêtre
WIDTH, HEIGHT = 800, 800
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Mouvement circulaire simple (cos / sin)")

clock = pygame.time.Clock()

# ==========================================================
# 2. CENTRE DU MOUVEMENT
# ==========================================================
# Tous les objets vont tourner autour de ce point central.

CENTER_X = WIDTH // 2
CENTER_Y = HEIGHT // 2

# ==========================================================
# 3. PARAMÈTRES DU MOUVEMENT
# ==========================================================

angle = 0
# angle représente "où on en est" sur le cercle
# Il augmente doucement à chaque image

speed = 0.01
# vitesse de rotation
# PLUS C'EST PETIT → PLUS C'EST LENT ET OBSERVABLE

# ==========================================================
# 4. RAYONS DES TRAJECTOIRES
# ==========================================================
# Chaque objet a une distance différente par rapport au centre

radius_1 = 120
radius_2 = 200

# ==========================================================
# 5. LISTES POUR GARDER LES TRAJECTOIRES
# ==========================================================
# On stocke les anciennes positions pour voir les chemins

path_1 = []
path_2 = []

MAX_POINTS = 1000

# ==========================================================
# 6. BOUCLE PRINCIPALE
# ==========================================================

running = True
while running:

    # ----------------------------------
    # Gestion de la fermeture de la fenêtre
    # ----------------------------------
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

    # ======================================================
    # 7. CALCUL DES POSITIONS AVEC COS ET SIN
    # ======================================================
    # Idée clé à comprendre :
    #
    # cos(angle) donne la position horizontale
    # sin(angle) donne la position verticale
    #
    # Ensemble, ils décrivent un CERCLE

    angle += speed

    x1 = CENTER_X + radius_1 * math.cos(angle)
    y1 = CENTER_Y + radius_1 * math.sin(angle)

    x2 = CENTER_X + radius_2 * math.cos(angle * 0.6)
    y2 = CENTER_Y + radius_2 * math.sin(angle * 0.6)

    # On garde les positions pour dessiner les trajectoires
    path_1.append((x1, y1))
    path_2.append((x2, y2))

    if len(path_1) > MAX_POINTS:
        path_1.pop(0)

    if len(path_2) > MAX_POINTS:
        path_2.pop(0)

    # ======================================================
    # 8. AFFICHAGE
    # ======================================================

    screen.fill((0, 0, 0))

    # ----------------------------------
    # Dessin des trajectoires
    # ----------------------------------
    if len(path_1) > 1:
        pygame.draw.lines(screen, (100, 150, 255), False, path_1, 2)

    if len(path_2) > 1:
        pygame.draw.lines(screen, (200, 200, 200), False, path_2, 2)

    # ----------------------------------
    # Centre (point fixe)
    # ----------------------------------
    pygame.draw.circle(screen, (255, 200, 50), (CENTER_X, CENTER_Y), 10)

    # ----------------------------------
    # Objets en mouvement
    # ----------------------------------
    pygame.draw.circle(screen, (120, 180, 255), (int(x1), int(y1)), 6)
    pygame.draw.circle(screen, (220, 220, 220), (int(x2), int(y2)), 6)

    pygame.display.flip()
    clock.tick(60)

pygame.quit()
