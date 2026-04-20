
#la fusion de deux dict : maniere mdoerne
d1= { 'a0': 1, 'b': 2}
d2 = {'b': 3, 'c': 4}
fusion = d1 | d2

print(fusion)

#trouver l' element le plus fréquent

votes = ['A', 'B', 'A', 'C', 'A', 'B']

from collections import Counter
top = Counter(votes).most_common(1)[0][0]
print(top)

#supp les doublons sans ordre

liste = [1,5,2,1,5,3]
print(list(set(liste)))

# supp doublons en respectant l'ordre

clean = list(dict.fromkeys(liste))

print(clean)

fonctions = []
for i in range(3):
    fonctions.append(lambda x=i:x)
print([f() for f in fonctions])    